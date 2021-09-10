#pragma once

#include <cstdint>
#include <fstream>
#include <string>

namespace pensieve::io {

class Source
{
  public:
    virtual ~Source(){};
    virtual void close() = 0;
    virtual bool is_open() = 0;
    virtual void read(char* result, ssize_t length) = 0;
    virtual void getline(std::string& result, char delimiter) = 0;
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
    void read(char* result, ssize_t length) override;
    void getline(std::string& result, char delimiter) override;

  private:
    void _close();
    const std::string& d_file_name;
    std::ifstream d_stream;
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
    void read(char* result, ssize_t length) override;
    void getline(std::string& result, char delimiter) override;

  private:
    bool eof();
    void _close();
    int d_sockfd{-1};
    bool d_is_open{false};
};

}  // namespace pensieve::io
