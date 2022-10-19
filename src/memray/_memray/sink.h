#pragma once

#include <cerrno>
#include <memory>
#include <string>
#include <unistd.h>

#include "records.h"

namespace memray::io {

class Sink
{
  public:
    virtual ~Sink(){};
    virtual bool writeAll(const char* data, size_t length) = 0;
    virtual bool seek(off_t offset, int whence) = 0;
    virtual std::unique_ptr<Sink> cloneInChildProcess() = 0;
    virtual bool flush()
    {
        return true;
    }
};

class FileSink : public memray::io::Sink
{
  public:
    FileSink(const std::string& file_name, bool overwrite, bool compress);
    ~FileSink() override;
    FileSink(FileSink&) = delete;
    FileSink(FileSink&&) = delete;
    void operator=(const FileSink&) = delete;
    void operator=(const FileSink&&) = delete;

    bool writeAll(const char* data, size_t length) override;
    bool seek(off_t offset, int whence) override;
    std::unique_ptr<Sink> cloneInChildProcess() override;

  private:
    void compress() noexcept;
    bool grow(size_t needed);
    bool slideWindow();
    size_t bytesBeyondBufferNeedle();

    std::string d_filename;
    std::string d_fileNameStem;
    bool d_compress{1};
    int d_fd{-1};
    size_t d_fileSize{0};
    const size_t BUFFER_SIZE{16 * 1024 * 1024};  // 16 MiB
    size_t d_bufferOffset{0};
    char* d_buffer{nullptr};
    char* d_bufferEnd{nullptr};  // exclusive
    char* d_bufferNeedle{nullptr};
};

class SocketSink : public Sink
{
  public:
    explicit SocketSink(std::string host, uint16_t port);
    ~SocketSink() override;

    SocketSink(SocketSink&) = delete;
    SocketSink(SocketSink&&) = delete;
    void operator=(const SocketSink&) = delete;
    void operator=(const SocketSink&&) = delete;

    bool writeAll(const char* data, size_t length) override;
    bool seek(off_t offset, int whence) override;
    std::unique_ptr<Sink> cloneInChildProcess() override;
    bool flush() override;

  private:
    size_t freeSpaceInBuffer();
    void open();
    bool _flush();

    const std::string d_host;
    uint16_t d_port;
    int d_socket_fd{-1};
    bool d_socket_open{false};

    const size_t BUFFER_SIZE{PIPE_BUF};
    std::unique_ptr<char[]> d_buffer{nullptr};
    char* d_bufferNeedle{nullptr};
};

class NullSink : public Sink
{
  public:
    ~NullSink() override;
    bool writeAll(const char* data, size_t length) override;
    bool seek(off_t offset, int whence) override;
    std::unique_ptr<Sink> cloneInChildProcess() override;
};

}  // namespace memray::io
