#pragma once

#include <cerrno>
#include <memory>
#include <string>
#include <unistd.h>

#include "records.h"

namespace pensieve::io {

class Sink
{
  public:
    virtual ~Sink(){};
    virtual bool writeAll(const char* data, size_t length) = 0;
    virtual bool seek(off_t offset, int whence) = 0;
};

class FileSink : public pensieve::io::Sink
{
  public:
    FileSink(const std::string& file_name, bool exist_ok);
    ~FileSink() override;
    FileSink(FileSink&) = delete;
    FileSink(FileSink&&) = delete;
    void operator=(const FileSink&) = delete;
    void operator=(const FileSink&&) = delete;

    bool writeAll(const char* data, size_t length) override;
    bool seek(off_t offset, int whence) override;

  private:
    int d_fd{-1};
};

class SocketSink : public Sink
{
  public:
    explicit SocketSink(std::string host, uint16_t port);
    ~SocketSink() override;

    SocketSink(SocketSink&) = delete;
    SocketSink(SocketSink&&) = delete;
    void operator=(const FileSink&) = delete;
    void operator=(const FileSink&&) = delete;

    bool writeAll(const char* data, size_t length) override;
    bool seek(off_t offset, int whence) override;

  private:
    void open();

    const std::string d_host;
    uint16_t d_port;
    int d_socket_fd{-1};
    bool d_socket_open{false};
};

}  // namespace pensieve::io
