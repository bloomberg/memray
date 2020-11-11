
#include "records.h"

namespace pensieve::tracking_api {

std::ostream&
operator<<(std::ostream& os, const PyFrameRecord& frame)
{
    os << frame.filename << ":" << frame.function_name << ":" << frame.lineno;
    return os;
}

Frame::Frame(PyFrameRecord& pyframe)
: function_name(pyframe.function_name)
, filename(pyframe.filename)
, lineno(pyframe.lineno)
{
}
}  // namespace pensieve::tracking_api
