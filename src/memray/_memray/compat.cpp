#include "compat.h"

#include <exception>
#include <limits>

namespace memray::compat {

void
setprofileAllThreads(Py_tracefunc func, PyObject* arg)
{
    assert(PyGILState_Check());
#if PY_VERSION_HEX >= 0x030C00F0
    PyEval_SetProfileAllThreads(func, arg);
#else
    PyThreadState* this_tstate = PyThreadState_Get();
    PyInterpreterState* interp = threadStateGetInterpreter(this_tstate);
    for (PyThreadState* tstate = PyInterpreterState_ThreadHead(interp); tstate != nullptr;
         tstate = PyThreadState_Next(tstate))
    {
        if (_PyEval_SetProfile(tstate, func, arg) < 0) {
            _PyErr_WriteUnraisableMsg("in PyEval_SetProfileAllThreads", nullptr);
        }
    }
#endif
}

// Constants for older Python versions
static const int NO_LINE_NUMBER = -0x80;

// Code location info kinds for Python 3.11+
typedef enum _PyCodeLocationInfoKind {
    PY_CODE_LOCATION_INFO_SHORT0 = 0,
    PY_CODE_LOCATION_INFO_ONE_LINE0 = 10,
    PY_CODE_LOCATION_INFO_ONE_LINE1 = 11,
    PY_CODE_LOCATION_INFO_ONE_LINE2 = 12,

    PY_CODE_LOCATION_INFO_NO_COLUMNS = 13,
    PY_CODE_LOCATION_INFO_LONG = 14,
    PY_CODE_LOCATION_INFO_NONE = 15
} _PyCodeLocationInfoKind;

// Parse line table for Python 3.11+
inline bool
parseLinetable311(uintptr_t addrq, const std::string& linetable, int firstlineno, LocationInfo* info)
{
    addrq /= 2;  // Convert from instruction offset to byte offset
    const uint8_t* ptr = reinterpret_cast<const uint8_t*>(linetable.data());
    const uint8_t* const end = ptr + linetable.size();
    uint64_t addr = 0;
    info->lineno = firstlineno;

    struct InvalidLinetable : std::exception
    {
    };

    auto read_byte = [&]() -> uint8_t {
        if (ptr == end) {
            throw InvalidLinetable{};
        }
        return *ptr++;
    };

    auto scan_varint = [&]() {
        unsigned int read = read_byte();
        unsigned int val = read & 63;
        unsigned int shift = 0;
        while (read & 64) {
            read = read_byte();
            shift += 6;
            if (shift >= std::numeric_limits<unsigned int>::digits) {
                // Shifting this much would be UB, so the table is malformed.
                throw InvalidLinetable{};
            }
            val |= (read & 63) << shift;
        }
        return val;
    };

    auto scan_signed_varint = [&]() {
        unsigned int uval = scan_varint();
        int sval = uval >> 1;
        int sign = (uval & 1) ? -1 : 1;
        return sign * sval;
    };

    try {
        while (ptr < end) {
            uint8_t first_byte = read_byte();
            uint8_t code = (first_byte >> 3) & 15;
            size_t length = (first_byte & 7) + 1;
            uintptr_t end_addr = addr + length;
            switch (code) {
                case PY_CODE_LOCATION_INFO_NONE: {
                    break;
                }
                case PY_CODE_LOCATION_INFO_LONG: {
                    int line_delta = scan_signed_varint();
                    info->lineno += line_delta;
                    info->end_lineno = info->lineno + scan_varint();
                    info->column = scan_varint() - 1;
                    info->end_column = scan_varint() - 1;
                    break;
                }
                case PY_CODE_LOCATION_INFO_NO_COLUMNS: {
                    int line_delta = scan_signed_varint();
                    info->lineno += line_delta;
                    info->column = info->end_column = -1;
                    break;
                }
                case PY_CODE_LOCATION_INFO_ONE_LINE0:
                case PY_CODE_LOCATION_INFO_ONE_LINE1:
                case PY_CODE_LOCATION_INFO_ONE_LINE2: {
                    int line_delta = code - 10;
                    info->lineno += line_delta;
                    info->end_lineno = info->lineno;
                    info->column = read_byte();
                    info->end_column = read_byte();
                    break;
                }
                default: {
                    uint8_t second_byte = read_byte();
                    if ((second_byte & 128) != 0) {
                        throw InvalidLinetable{};
                    }
                    info->column = code << 3 | (second_byte >> 4);
                    info->end_column = info->column + (second_byte & 15);
                    break;
                }
            }
            if (addr <= addrq && end_addr > addrq) {
                return true;
            }
            addr = end_addr;
        }
    } catch (const InvalidLinetable&) {
        return false;
    }
    return false;
}

// Parse line table for Python 3.10
inline bool
parseLinetable310(
        const uintptr_t instruction_offset,
        const std::string& linetable,
        int firstlineno,
        LocationInfo* info)
{
    if (linetable.size() % 2 != 0) {
        return false;  // A valid linetable has 2 bytes per entry
    }

    int code_lineno = firstlineno;

    // Word-code is two bytes, so the actual limit in the table is 2 * the instruction index
    std::string::size_type last_executed_instruction = instruction_offset << 1;

    for (std::string::size_type i = 0, current_instruction = 0; i + 1 < linetable.size();) {
        unsigned char start_delta = linetable[i++];
        signed char line_delta = linetable[i++];
        current_instruction += start_delta;
        code_lineno += (line_delta == NO_LINE_NUMBER) ? 0 : line_delta;
        if (current_instruction > last_executed_instruction) {
            break;
        }
    }

    info->lineno = code_lineno;
    info->end_lineno = code_lineno;
    info->column = -1;
    info->end_column = -1;
    return true;
}

// Parse line table for Python 3.9 and earlier (co_lnotab format)
inline bool
parseLinetable39(
        const uintptr_t instruction_offset,
        const std::string& linetable,
        int firstlineno,
        LocationInfo* info)
{
    if (linetable.size() % 2 != 0) {
        return false;  // A valid linetable has 2 bytes per entry
    }

    int code_lineno = firstlineno;

    for (std::string::size_type i = 0, bc = 0; i + 1 < linetable.size();
         code_lineno += static_cast<int8_t>(linetable[i++]))
    {
        bc += linetable[i++];
        if (bc > instruction_offset) {
            break;
        }
    }

    info->lineno = code_lineno;
    info->end_lineno = code_lineno;
    info->column = -1;
    info->end_column = -1;
    return true;
}

bool
parseLinetable(
        int python_version,
        const std::string& linetable,
        uintptr_t addrq,
        int firstlineno,
        LocationInfo* info)
{
    if (linetable.empty()) {
        info->lineno = firstlineno;
        info->end_lineno = firstlineno;
        info->column = -1;
        info->end_column = -1;
        return true;
    }

    if (python_version >= 0x030B0000) {
        return parseLinetable311(addrq, linetable, firstlineno, info);
    } else if (python_version >= 0x030A0000) {
        return parseLinetable310(addrq, linetable, firstlineno, info);
    } else {
        return parseLinetable39(addrq, linetable, firstlineno, info);
    }
}

}  // namespace memray::compat
