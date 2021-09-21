
#include <cerrno>
#include <cstdio>

#include <fcntl.h>
#include <netdb.h>
#include <stdexcept>
#include <sys/socket.h>

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

SocketSink::SocketSink(int port)
: d_port(port)
{
    open();
}

bool
SocketSink::writeAll(const char* data, size_t length)
{
    while (length) {
        ssize_t ret = ::send(d_socket_fd, data, length, 0);
        if (ret < 0 && errno != EINTR) {
            std::cerr << "Encountered error in 'send' call: " << strerror(errno);
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
    struct addrinfo hints;
    struct addrinfo* servinfo;
    struct addrinfo* p;
    struct sockaddr_storage their_addr;
    socklen_t sin_size;
    int yes = 1;
    int rv;

    memset(&hints, 0, sizeof hints);
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_PASSIVE;  // bind to all of my IP addresses

    std::string port_str = std::to_string(d_port);
    if ((rv = getaddrinfo(nullptr, port_str.c_str(), &hints, &servinfo)) != 0) {
        LOG(ERROR) << "Encountered error in 'getaddrinfo' call: " << gai_strerror(rv);
        throw IoError{"Failed to resolve host IP and port"};
    }

    // loop through all the results and bind to the first we can
    for (p = servinfo; p != nullptr; p = p->ai_next) {
        if ((sockfd = socket(p->ai_family, p->ai_socktype, p->ai_protocol)) == -1) {
            LOG(WARNING) << "Encountered error in 'socket' call: " << strerror(errno);
            continue;
        }

        if (setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(int)) == -1) {
            ::close(sockfd);
            freeaddrinfo(servinfo);
            LOG(ERROR) << "Encountered error in 'setsockopt' call: " << strerror(errno);
            throw IoError{"Failed to set socket options"};
        }

        if (bind(sockfd, p->ai_addr, p->ai_addrlen) == -1) {
            ::close(sockfd);
            LOG(WARNING) << "Encountered error in 'bind' call: " << strerror(errno);
            continue;
        }

        break;
    }

    freeaddrinfo(servinfo);

    if (p == nullptr) {
        throw IoError{"Failed to bind to port"};
    }

    if (listen(sockfd, 1) == -1) {
        ::close(sockfd);
        throw IoError{"Encountered error in listen call"};
    }

    LOG(DEBUG) << "Waiting for connections";
    sin_size = sizeof their_addr;
    d_socket_fd = accept(sockfd, (struct sockaddr*)&their_addr, &sin_size);
    ::close(sockfd);
    if (d_socket_fd == -1) {
        LOG(ERROR) << "Encountered error in 'accept' call: " << strerror(errno);
        throw IoError{"accept failed"};
    }

    d_socket_open = true;
}

}  // namespace pensieve::io
