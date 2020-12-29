#include "record_writer.h"

namespace pensieve::tracking_api {

RecordWriter::RecordWriter(const std::string& file_name)
: d_buffer(new char[BUFFER_CAPACITY]{0})
{
    fd = ::open(file_name.c_str(), O_CREAT | O_WRONLY | O_CLOEXEC, 0644);
    if (fd < 0) {
        std::runtime_error("Could not open file for writing: " + file_name);
    }
}

RecordWriter::~RecordWriter()
{
    ::close(fd);
}

bool
RecordWriter::flush() noexcept
{
    std::lock_guard<std::mutex> lock(d_mutex);
    return _flush();
}

bool
RecordWriter::_flush() noexcept
{
    if (!d_used_bytes) {
        return true;
    }

    int ret = 0;
    do {
        ret = ::write(fd, d_buffer.get(), d_used_bytes);
    } while (ret < 0 && errno == EINTR);

    if (ret < 0) {
        return false;
    }

    d_used_bytes = 0;

    return true;
}

}  // namespace pensieve::tracking_api