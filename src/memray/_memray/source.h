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
    virtual ~Source() {};
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

// Wraps a Source, reading from it in large chunks and serving reads from the
// buffered data, to minimize the number of virtual calls and system calls.
//
// Depending on the kind of Source being wrapped, data may be buffered more
// than once before reaching this buffer:
//   - SocketSource has no buffer of its own; we recv() directly into ours.
//   - An uncompressed FileSource reads through a std::ifstream. Since we
//     always request BUFFER_SIZE bytes, which is larger than the ifstream's
//     own buffer, the standard library can bypass its buffer and read
//     directly into ours. Only smaller reads (e.g. at the very end of the
//     readable portion of the file) are double buffered.
//   - A compressed FileSource reads compressed data from the std::ifstream
//     into the LZ4 decompressor's source buffer, decompresses it into the
//     decompressor's destination buffer, and copies it from there into ours.
//     Both LZ4 buffers are sized to match BUFFER_SIZE so that each refill of
//     our buffer needs only a small number of reads and decompression calls.
class BufferedSource
{
  public:
    static constexpr size_t BUFFER_SIZE = 64 * 1024;

    explicit BufferedSource(std::unique_ptr<Source> unbuffered_source);
    ~BufferedSource();
    void close();
    bool is_open() const;
    bool read(char* destination, size_t length);
    bool getline(std::string& result, char delimiter);

  private:
    size_t refillBuffer();
    std::unique_ptr<Source> d_unbuffered_source;
    std::array<char, BUFFER_SIZE> d_buffer;
    std::atomic<bool> d_is_open{false};
    size_t d_buffer_pos{};
    size_t d_buffer_end{};
};

}  // namespace memray::io
