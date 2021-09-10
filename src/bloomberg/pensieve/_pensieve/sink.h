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
    virtual bool write(const char* data, size_t length) = 0;
    virtual void seek(off_t offset, int whence) = 0;
    virtual void close() = 0;
};

class FileSink : public pensieve::io::Sink
{
  public:
    FileSink(const std::string& file_name);
    ~FileSink() override;
    FileSink(FileSink&) = delete;
    FileSink(FileSink&&) = delete;
    void operator=(const FileSink&) = delete;
    void operator=(const FileSink&&) = delete;

    bool write(const char* data, size_t length) override;
    void seek(off_t offset, int whence) override;
    void close() override;

  private:
    void _close() const;

    int d_fd{-1};
};

class SocketSink : public Sink
{
  public:
    explicit SocketSink(int port);
    ~SocketSink() override;

    SocketSink(SocketSink&) = delete;
    SocketSink(SocketSink&&) = delete;
    void operator=(const FileSink&) = delete;
    void operator=(const FileSink&&) = delete;

    bool write(const char* data, size_t length) override;
    void seek(off_t offset, int whence) override;
    void close() override;

  private:
    void _close();

    int d_socket_fd{-1};
    bool d_socket_open{false};
};

}  // namespace pensieve::io
