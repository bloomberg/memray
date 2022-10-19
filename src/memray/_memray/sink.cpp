#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cerrno>
#include <cstdio>

#include <arpa/inet.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>
#include <utility>

#include "exceptions.h"
#include "lz4_stream.h"
#include "sink.h"

namespace memray::io {

using namespace memray::exception;

namespace {  // unnamed

#ifdef __APPLE__
static int
posix_fallocate(int fd, off_t offset, off_t len)
{
    fstore_t store = {F_ALLOCATEALL, F_PEOFPOSMODE, 0, len, 0};
    int res = ::fcntl(fd, F_PREALLOCATE, &store);
    if (res != 0) {
        return errno;
    }
    do {
        res = ::ftruncate(fd, offset + len);
    } while (res != 0 && errno == EINTR);
    if (res != 0) {
        return errno;
    }
    return 0;
}
#endif

std::string
removeSuffix(const std::string& s, const std::string& suffix)
{
    if (s.size() < suffix.size()) {
        return s;  // Too short to end with suffix.
    }

    if (0 != s.compare(s.size() - suffix.size(), std::string::npos, suffix)) {
        return s;  // Long enough, but doesn't end with suffix.
    }

    return s.substr(0, s.size() - suffix.size());
}

}  // unnamed namespace

bool
FileSink::writeAll(const char* data, size_t length)
{
    // If the file isn't big enough for all this data, grow it.
    size_t maxWritableWithoutGrowing = bytesBeyondBufferNeedle();
    if (maxWritableWithoutGrowing < length) {
        if (!grow(length - maxWritableWithoutGrowing)) {
            return false;
        }
        assert(bytesBeyondBufferNeedle() >= length);
    }

    while (length) {
        if (d_bufferNeedle == d_bufferEnd) {
            // We've reached the end of our window. Slide it forward.
            if (!seek(d_bufferOffset + (d_bufferEnd - d_buffer), SEEK_SET)) {
                return false;
            }
        }

        size_t available = d_bufferEnd - d_bufferNeedle;
        size_t toCopy = std::min(available, length);
        memcpy(d_bufferNeedle, data, toCopy);
        d_bufferNeedle += toCopy;
        data += toCopy;
        length -= toCopy;
    }
    return true;
}

FileSink::FileSink(const std::string& file_name, bool overwrite, bool compress)
: d_filename(file_name)
, d_fileNameStem(removeSuffix(file_name, "." + std::to_string(::getpid())))
, d_compress(compress)
{
    int flags = O_CREAT | O_RDWR | O_TRUNC | O_CLOEXEC;
    if (!overwrite) {
        flags |= O_EXCL;
    }
    do {
        d_fd = ::open(file_name.c_str(), flags, 0644);
    } while (d_fd < 0 && errno == EINTR);
    if (d_fd < 0) {
        throw IoError{"Could not create output file " + file_name + ": " + std::string(strerror(errno))};
    }
}

bool
FileSink::seek(off_t offset, int whence)
{
    // Don't allow seeking relative to the current offset. We move the offset
    // when we grow the file, and don't move it when we write, so users can't
    // possibly know what the offset is.
    if (whence != SEEK_SET && whence != SEEK_END) {
        errno = EINVAL;
        return false;
    }

    // Convert offset to an absolute position, if it isn't already
    if (whence != SEEK_SET) {
        offset = lseek(d_fd, offset, whence);
    }

    if (offset < 0) {
        errno = EINVAL;
        return false;
    }

    // Free our existing buffer, if any
    if (d_buffer && 0 != munmap(d_buffer, BUFFER_SIZE)) {
        return false;
    }

    // Note: It is OK to map beyond the end of the file,
    //       though not to write beyond the end.
    d_buffer = static_cast<char*>(mmap(d_buffer, BUFFER_SIZE, PROT_WRITE, MAP_SHARED, d_fd, offset));
    if (d_buffer == MAP_FAILED) {
        d_buffer = nullptr;
        return false;
    }
    d_bufferNeedle = d_buffer;
    d_bufferOffset = offset;

    size_t bytesRemaining = d_fileSize - offset;
    d_bufferEnd = d_buffer + std::min(bytesRemaining, BUFFER_SIZE);

    return true;
}

bool
FileSink::grow(size_t needed)
{
    static size_t pagesize = sysconf(_SC_PAGESIZE);
    // Grow to next multiple of the page size that is strictly > 110% of current size + needed
    size_t new_size = (d_fileSize + needed) * 1.1;
    new_size = (new_size / pagesize + 1) * pagesize;
    assert(new_size > d_fileSize);  // check for overflow

    off_t delta = new_size - d_fileSize;
    int rc;
    do {
        // posix_fallocate returns an error number instead of setting errno
        rc = posix_fallocate(d_fd, d_fileSize, delta);
    } while (rc == EINTR);

    if (rc != 0) {
        errno = rc;
        return false;
    }

    d_fileSize = new_size;
    assert(static_cast<off_t>(d_fileSize) == lseek(d_fd, 0, SEEK_END));

    return true;
}

size_t
FileSink::bytesBeyondBufferNeedle()
{
    size_t bytesBeyondBuffer = d_fileSize - d_bufferOffset;
    size_t positionWithinBuffer = d_bufferNeedle - d_buffer;
    return bytesBeyondBuffer - positionWithinBuffer;
}

std::unique_ptr<Sink>
FileSink::cloneInChildProcess()
{
    std::string file_name = d_fileNameStem + "." + std::to_string(::getpid());
    return std::make_unique<FileSink>(file_name, true, d_compress);
}

void
FileSink::compress() noexcept
{
    std::ifstream in_file(d_filename);
    std::string tmp_filename = d_filename + ".lz4.tmp";
    std::ofstream out_file(tmp_filename);
    bool success = true;
    constexpr size_t bufsize = 4 * 1024;

    // lz4_stream is using exceptions rather than failbit/badbit
    try {
        lz4_stream::ostream lz4_stream(out_file);
        std::vector<char> buf(bufsize);
        while (in_file) {
            in_file.read(&buf[0], buf.size());
            lz4_stream.write(&buf[0], in_file.gcount());
        }
    } catch (...) {
        success = false;
    }

    out_file.close();
    if (!in_file.eof() || !out_file) {
        success = false;
    }

    if (!success) {
        std::cerr << "Failed to compress input file" << std::endl;
        ::unlink(tmp_filename.c_str());
    } else if (0 != std::rename(tmp_filename.c_str(), d_filename.c_str())) {
        std::perror("Error moving compressed file back to original name");
        ::unlink(tmp_filename.c_str());
    }
}

FileSink::~FileSink()
{
    if (d_buffer) {
        if (0 != munmap(d_buffer, BUFFER_SIZE)) {
            LOG(ERROR) << "Failed to unmap output file: " << strerror(errno);
        }
        d_buffer = d_bufferNeedle = d_bufferEnd = nullptr;
    }
    if (d_fd != -1) {
        ::close(d_fd);
    }

    if (d_compress) {
        compress();
    }
}

SocketSink::SocketSink(std::string host, uint16_t port)
: d_host(std::move(host))
, d_port(port)
, d_buffer(new char[BUFFER_SIZE])
, d_bufferNeedle(d_buffer.get())
{
    open();
}

size_t
SocketSink::freeSpaceInBuffer()
{
    return BUFFER_SIZE - (d_bufferNeedle - d_buffer.get());
}

bool
SocketSink::writeAll(const char* data, size_t length)
{
    while (freeSpaceInBuffer() < length) {
        size_t toWrite = freeSpaceInBuffer();
        memcpy(d_bufferNeedle, data, toWrite);
        d_bufferNeedle += toWrite;
        data += toWrite;
        length -= toWrite;
        if (!flush()) {
            return false;
        }
    }

    memcpy(d_bufferNeedle, data, length);
    d_bufferNeedle += length;
    return true;
}

bool
SocketSink::flush()
{
    return _flush();
}

bool
SocketSink::_flush()
{
    const char* data = d_buffer.get();
    size_t length = d_bufferNeedle - data;

    d_bufferNeedle = d_buffer.get();

    while (length) {
        ssize_t ret = ::send(d_socket_fd, data, length, 0);
        if (ret < 0 && errno != EINTR) {
            return false;
        } else if (ret >= 0) {
            data += ret;
            length -= ret;
        }
    }
    return true;
}

bool
SocketSink::seek(__attribute__((unused)) off_t offset, __attribute__((unused)) int whence)
{
    return false;
}

std::unique_ptr<Sink>
SocketSink::cloneInChildProcess()
{
    // We can't clone ourselves. We can't start a new TCP stream and block
    // waiting for a client, and we can't create a new sink that shares the
    // same socket because the client would see writes from all processes
    // interleaved.
    return {};
}

SocketSink::~SocketSink()
{
    if (d_socket_open) {
        _flush();
        ::close(d_socket_fd);
        d_socket_open = false;
    }
}

void
SocketSink::open()
{
    int sockfd;
    struct sockaddr_storage their_addr;
    socklen_t sin_size;
    int yes = 1;

    sockaddr_in si;
    si.sin_family = AF_INET;
    si.sin_addr.s_addr = ::inet_addr(d_host.c_str());
    si.sin_port = htons(d_port);

    if ((sockfd = socket(PF_INET, SOCK_STREAM, 0)) == -1) {
        LOG(ERROR) << "Encountered error in 'socket' call: " << strerror(errno);
        throw IoError{"Failed to open socket"};
    }

    if (setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(int)) == -1) {
        ::close(sockfd);
        LOG(ERROR) << "Encountered error in 'setsockopt' call: " << strerror(errno);
        throw IoError{"Failed to set socket options"};
    }

    if (bind(sockfd, (sockaddr*)&si, sizeof si) == -1) {
        ::close(sockfd);
        LOG(WARNING) << "Encountered error in 'bind' call: " << strerror(errno);
        throw IoError{"Failed to bind to host and port"};
    }

    if (listen(sockfd, 1) == -1) {
        ::close(sockfd);
        throw IoError{"Encountered error in listen call"};
    }

    LOG(DEBUG) << "Waiting for connections";
    sin_size = sizeof their_addr;

    bool async_err = false;
    do {
        Py_BEGIN_ALLOW_THREADS;
        d_socket_fd = accept(sockfd, (struct sockaddr*)&their_addr, &sin_size);
        Py_END_ALLOW_THREADS;
    } while (d_socket_fd != 0 && errno == EINTR && !(async_err = PyErr_CheckSignals()));
    ::close(sockfd);

    if (async_err) {
        return;
    }

    if (d_socket_fd == -1) {
        LOG(ERROR) << "Encountered error in 'accept' call: " << strerror(errno);
        throw IoError{strerror(errno)};
    }

    d_socket_open = true;
}

NullSink::~NullSink()
{
}

bool
NullSink::writeAll(const char*, size_t)
{
    return true;
}

bool
NullSink::seek(off_t, int)
{
    return true;
}

std::unique_ptr<Sink>
NullSink::cloneInChildProcess()
{
    return std::make_unique<NullSink>();
}

}  // namespace memray::io
