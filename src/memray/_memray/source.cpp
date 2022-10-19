#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cerrno>
#include <cstring>
#include <iostream>
#include <netdb.h>
#include <stdexcept>
#include <sys/socket.h>
#include <unistd.h>

#include <chrono>
#include <thread>

#include "exceptions.h"
#include "logging.h"
#include "source.h"

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

bool
FileSource::read(char* stream, ssize_t length)
{
    if (d_stream->read(stream, length).fail()) {
        return false;
    }
    d_bytes_read += length;
    if (d_readable_size && d_bytes_read > d_readable_size) {
        return false;
    }
    return true;
}

bool
FileSource::getline(std::string& result, char delimiter)
{
    std::getline(*d_stream, result, delimiter);
    if (!d_stream) {
        return false;
    }
    d_bytes_read += result.size() + 1;
    if (d_readable_size && d_bytes_read > d_readable_size) {
        return false;
    }
    return true;
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

SocketBuf::SocketBuf(int socket_fd)
: d_sockfd(socket_fd)
{
    setg(d_buf, d_buf, d_buf);
}

void
SocketBuf::close()
{
    d_open = false;
}

int
SocketBuf::underflow()
{
    if (gptr() < egptr()) {
        return traits_type::to_int_type(*gptr());
    }

    ssize_t bytes_read;
    do {
        bytes_read = ::recv(d_sockfd, d_buf, MAX_BUF_SIZE, 0);
    } while (bytes_read < 0 && errno == EINTR);

    if (bytes_read < 0) {
        if (d_open) {
            LOG(ERROR) << "Encountered error in 'recv' call: " << strerror(errno);
        }
        return traits_type::eof();
    }

    if (bytes_read == 0) {
        return traits_type::eof();
    }

    setg(d_buf, d_buf, d_buf + bytes_read);
    return traits_type::to_int_type(*gptr());
}

std::streamsize
SocketBuf::xsgetn(char* destination, std::streamsize length)
{
    std::streamsize needed = length;
    while (needed > 0) {
        if (gptr() == egptr()) {
            // Buffer empty. Get some new data, and throw if we can't.
            if (underflow() == traits_type::eof()) {
                return traits_type::eof();
            }
        }

        std::streamsize available = egptr() - gptr();
        std::streamsize to_copy = std::min(available, needed);

        ::memcpy(destination, gptr(), to_copy);
        gbump(static_cast<int>(to_copy));
        destination += to_copy;
        needed -= to_copy;
    }
    return length;
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
    d_socket_buf = std::make_unique<SocketBuf>(d_sockfd);
}

bool
SocketSource::read(char* result, ssize_t length)
{
    if (!d_is_open) {
        return false;
    }
    return d_socket_buf->sgetn(result, length) != SocketBuf::traits_type::eof();
}

void
SocketSource::_close()
{
    if (!d_is_open) {
        return;
    }
    d_is_open = false;
    d_socket_buf->close();
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

bool
SocketSource::getline(std::string& result, char delimiter)
{
    char buf;
    while (true) {
        buf = static_cast<char>(d_socket_buf->sbumpc());
        if (buf == delimiter || buf == SocketBuf::traits_type::eof()) {
            if (!d_is_open) {
                return false;
            }
            break;
        }
        result.push_back(buf);
    }
    return true;
}

SocketSource::~SocketSource()
{
    _close();
}

}  // namespace memray::io
