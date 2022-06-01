#pragma once

#include <atomic>
#include <cstdint>
#include <fstream>
#include <memory>
#include <string>

#include "lz4_stream.h"

namespace memray::io {

const int MAX_BUF_SIZE = 4096;

class Source
{
  public:
    virtual ~Source(){};
    virtual void close() = 0;
    virtual bool is_open() = 0;
    virtual bool read(char* result, ssize_t length) = 0;
    virtual bool getline(std::string& result, char delimiter) = 0;
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
    bool read(char* result, ssize_t length) override;
    bool getline(std::string& result, char delimiter) override;

  private:
    void _close();
    void findReadableSize();
    const std::string& d_file_name;
    std::shared_ptr<std::ifstream> d_raw_stream;
    std::shared_ptr<std::istream> d_stream;
    std::streamoff d_readable_size{};
    std::streamoff d_bytes_read{};
};

class SocketBuf : public std::streambuf
{
  public:
    explicit SocketBuf(int socket_fd);
    void close();

  private:
    int underflow() override;
    std::streamsize xsgetn(char_type* s, std::streamsize n) override;
    int d_sockfd{-1};
    char d_buf[MAX_BUF_SIZE];
    std::atomic<bool> d_open{true};
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
    bool read(char* result, ssize_t length) override;
    bool getline(std::string& result, char delimiter) override;

  private:
    void _close();
    int d_sockfd{-1};
    std::atomic<bool> d_is_open{false};
    std::unique_ptr<SocketBuf> d_socket_buf;
};

}  // namespace memray::io
