#include <cerrno>
#include <cstdio>

#include <arpa/inet.h>
#include <fcntl.h>
#include <netdb.h>
#include <stdexcept>
#include <sys/socket.h>
#include <utility>

#include <Python.h>

#include "exceptions.h"
#include "sink.h"

namespace pensieve::io {

using namespace pensieve::exception;

bool
FileSink::writeAll(const char* data, size_t length)
{
    while (length) {
        ssize_t ret = ::write(d_fd, data, length);
        if (ret < 0 && errno != EINTR) {
            return false;
        } else if (ret >= 0) {
            data += ret;
            length -= ret;
        }
    }
    return true;
}
FileSink::FileSink(const std::string& file_name)
{
    d_fd = open(file_name.c_str(), O_CREAT | O_WRONLY | O_CLOEXEC | O_EXCL, 0644);
    if (d_fd < 0) {
        throw IoError{"Could not create output file " + file_name + ": " + std::string(strerror(errno))};
    }
}
bool
FileSink::seek(off_t offset, int whence)
{
    return -1 != lseek(d_fd, offset, whence);
}

FileSink::~FileSink()
{
    if (d_fd != -1) {
        ::close(d_fd);
    }
}

SocketSink::SocketSink(std::string host, uint16_t port)
: d_host(std::move(host))
, d_port(port)
{
    open();
}

bool
SocketSink::writeAll(const char* data, size_t length)
{
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

SocketSink::~SocketSink()
{
    if (d_socket_open) {
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

}  // namespace pensieve::io
