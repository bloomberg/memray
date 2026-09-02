#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cerrno>
#include <cstring>
#include <iostream>
#include <netdb.h>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <thread>

#include "exceptions.h"
#include "logging.h"
#include "source.h"

#include "lz4_stream.h"

using namespace memray::exception;

namespace memray::io {

FileSource::FileSource(const std::string& file_name)
: d_file_name(file_name)
{
    d_raw_stream = std::make_shared<std::ifstream>(d_file_name, std::ios::binary | std::ios::in);
    if (!(*d_raw_stream)) {
        throw IoError{"Could not open file " + file_name + ": " + std::string(strerror(errno))};
    }
    char lz4_magic[] = {0x04, 0x22, 0x4D, 0x18};
    char file_magic[sizeof(lz4_magic)] = {};
    d_raw_stream->read(file_magic, sizeof(file_magic));
    d_raw_stream->seekg(0, std::ios::beg);

    if (0 == memcmp(lz4_magic, file_magic, sizeof(lz4_magic))) {
        d_stream = std::make_shared<lz4_stream::istream>(*d_raw_stream);
    } else {
        d_stream = d_raw_stream;
        findReadableSize();
    }
}

ssize_t
FileSource::read(char* destination, ssize_t length)
{
    if (d_stream->fail() || d_bytes_read == d_readable_size) {
        return -1;
    }

    auto to_read = static_cast<std::streamsize>(length);
    if (d_readable_size != -1) {
        to_read = std::min(to_read, static_cast<std::streamsize>(d_readable_size - d_bytes_read));
    }

    d_stream->read(destination, to_read);
    const auto bytes_read = d_stream->gcount();
    d_bytes_read += bytes_read;
    return bytes_read;
}

void
FileSource::close()
{
    _close();
}

void
FileSource::findReadableSize()
{
    // We grow the file in chunks and then overwrite the zero-filled data with
    // valid data, which means that if the process is killed in the middle of
    // tracking there will be some zero-filled bytes at the end of the file.
    // Ignore any zeroed bytes at the end of the file, assuming they resulted
    // from such premature termination (because when tracking ends successfully
    // a TRAILER record is written at the end of the valid data). We may ignore
    // some valid zero bytes that were part of a complete record, but since the
    // record type cannot be all zeroes, we will at worst lose one valid record
    // in order to recover from the file truncation. To ignore these, we count
    // the zeroed bytes at the end of the file, and make calls to read() and
    // getline() fail if they read into those bytes.
    d_raw_stream->seekg(-1, d_raw_stream->end);
    while (*d_raw_stream) {
        char c = d_raw_stream->peek();
        if (c != 0x00) {
            d_readable_size = d_raw_stream->tellg() + std::streamoff(1);
            break;
        }
        // If we're at BOF, this sets failbit and makes the loop break.
        d_raw_stream->seekg(-1, d_raw_stream->cur);
    }
    d_raw_stream->seekg(0, d_raw_stream->beg);
}

void
FileSource::_close()
{
    d_raw_stream->close();
}

bool
FileSource::is_open()
{
    return d_raw_stream->is_open();
}

FileSource::~FileSource()
{
    _close();
}

SocketSource::SocketSource(int port)
{
    struct addrinfo hints = {};
    struct addrinfo* all_addresses = nullptr;
    struct addrinfo* curr_address = nullptr;
    int rv;

    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;

    std::string port_str = std::to_string(port);
    while (curr_address == nullptr) {
        Py_BEGIN_ALLOW_THREADS;
        if ((rv = ::getaddrinfo(nullptr, port_str.c_str(), &hints, &all_addresses)) != 0) {
            Py_BLOCK_THREADS;
            LOG(ERROR) << "Encountered error in 'getaddrinfo' call: " << ::gai_strerror(rv);
            throw IoError{"Failed to resolve host IP and port"};
        }

        // loop through all the results and connect to the first we can
        for (curr_address = all_addresses; curr_address != nullptr; curr_address = curr_address->ai_next)
        {
            if ((d_sockfd = ::socket(
                         curr_address->ai_family,
                         curr_address->ai_socktype,
                         curr_address->ai_protocol))
                == -1)
            {
                continue;
            }

            if (::connect(d_sockfd, curr_address->ai_addr, curr_address->ai_addrlen) == -1) {
                ::close(d_sockfd);
                continue;
            }
            break;
        }
        if (curr_address == nullptr) {
            freeaddrinfo(all_addresses);
            LOG(DEBUG) << "No connection, sleeping before retrying...";
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
        }
        Py_END_ALLOW_THREADS;
        // Give a chance to check for signals arriving so we don't block the main thread.
        if (PyErr_CheckSignals() < 0) {
            break;
        }
    }
    if (curr_address == nullptr) {
        d_is_open = false;
        return;
    }

    freeaddrinfo(all_addresses);
    d_is_open = true;
}

ssize_t
SocketSource::read(char* result, ssize_t length)
{
    if (!d_is_open) {
        return -1;
    }

    ssize_t bytes_read;
    do {
        bytes_read = ::recv(d_sockfd, result, length, 0);
    } while (bytes_read < 0 && errno == EINTR);

    if (bytes_read < 0 && d_is_open) {
        LOG(ERROR) << "Encountered error in 'recv' call: " << strerror(errno);
    }

    return bytes_read;
}

void
SocketSource::_close()
{
    if (!d_is_open) {
        return;
    }
    d_is_open = false;
    ::shutdown(d_sockfd, SHUT_RDWR);
    ::close(d_sockfd);
}

void
SocketSource::close()
{
    _close();
}

bool
SocketSource::is_open()
{
    return d_is_open;
}

SocketSource::~SocketSource()
{
    _close();
}

BufferedSource::BufferedSource(std::unique_ptr<Source> unbuffered_source)
: d_unbuffered_source(std::move(unbuffered_source))
, d_is_open(d_unbuffered_source->is_open())
{
}

BufferedSource::~BufferedSource()
{
    close();
}

void
BufferedSource::close()
{
    if (d_is_open.exchange(false)) {
        d_unbuffered_source->close();
    }
}

bool
BufferedSource::is_open() const
{
    return d_is_open;
}

bool
BufferedSource::read(char* destination, size_t length)
{
    auto available = refillBuffer();

    // Fast path if the data we need is all in the buffer.
    // This makes a surprisingly large performance difference.
    if (length <= available) {
        std::memcpy(destination, d_buffer.data() + d_buffer_pos, length);
        d_buffer_pos += length;
        return true;
    }

    do {
        available = refillBuffer();
        if (!available) {
            return false;
        }
        auto bytes_to_copy = std::min(available, static_cast<size_t>(length));
        std::memcpy(destination, d_buffer.data() + d_buffer_pos, bytes_to_copy);
        destination += bytes_to_copy;
        d_buffer_pos += bytes_to_copy;
        length -= bytes_to_copy;
    } while (length > 0);
    return true;
}

bool
BufferedSource::getline(std::string& result, char delimiter)
{
    result.clear();
    while (refillBuffer()) {
        const char* begin = d_buffer.data() + d_buffer_pos;
        const auto available = d_buffer_end - d_buffer_pos;
        const char* end = static_cast<const char*>(std::memchr(begin, delimiter, available));
        if (end != nullptr) {
            result.append(begin, end);
            d_buffer_pos += end - begin + 1;
            return true;
        }

        result.append(begin, available);
        d_buffer_pos = d_buffer_end;
    }
    return false;
}

size_t
BufferedSource::refillBuffer()
{
    size_t available = d_buffer_end - d_buffer_pos;
    if (available) {
        return available;
    }

    auto bytes_read = d_unbuffered_source->read(d_buffer.data(), d_buffer.size());
    if (bytes_read <= 0) {
        return 0;
    }

    d_buffer_pos = 0;
    d_buffer_end = bytes_read;
    return bytes_read;
}

}  // namespace memray::io
