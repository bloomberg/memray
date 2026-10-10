#pragma once

#include <array>
#include <atomic>
#include <fstream>
#include <memory>
#include <string>

namespace memray::io {

class Source
{
  public:
    virtual ~Source(){};
    virtual void close() = 0;
    virtual bool is_open() = 0;
    virtual ssize_t read(char* result, ssize_t length) = 0;
};

class FileSource : public Source
{
  public:
    FileSource(FileSource& other) = delete;
    FileSource(FileSource&& other) = delete;
    void operator=(const FileSource&) = delete;
    void operator=(FileSource&&) = delete;

    FileSource(const std::string& file_name);
    ~FileSource() override;
    void close() override;
    bool is_open() override;
    ssize_t read(char* result, ssize_t length) override;

  private:
    void _close();
    void findReadableSize();
    const std::string& d_file_name;
    std::shared_ptr<std::ifstream> d_raw_stream;
    std::shared_ptr<std::istream> d_stream;
    std::streamoff d_readable_size{-1};
    std::streamoff d_bytes_read{};
};

class SocketSource : public Source
{
  public:
    SocketSource(SocketSource& other) = delete;
    SocketSource(SocketSource&& other) = delete;
    void operator=(const SocketSource&) = delete;
    void operator=(SocketSource&&) = delete;

    SocketSource(int port);
    ~SocketSource() override;
    void close() override;
    bool is_open() override;
    ssize_t read(char* result, ssize_t length) override;

  private:
    void _close();
    int d_sockfd{-1};
    std::atomic<bool> d_is_open{false};
};

class BufferedSource
{
  public:
    explicit BufferedSource(std::unique_ptr<Source> unbuffered_source);
    ~BufferedSource();
    void close();
    bool is_open() const;
    bool read(char* destination, size_t length);
    bool getline(std::string& result, char delimiter);

  private:
    size_t refillBuffer();
    static constexpr size_t BUFFER_SIZE = 64 * 1024;
    std::unique_ptr<Source> d_unbuffered_source;
    std::array<char, BUFFER_SIZE> d_buffer;
    std::atomic<bool> d_is_open{false};
    size_t d_buffer_pos{};
    size_t d_buffer_end{};
};

}  // namespace memray::io
