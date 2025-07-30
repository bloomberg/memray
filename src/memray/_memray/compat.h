#pragma once

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "frameobject.h"
#include <cassert>
#include <string>

namespace memray::compat {

inline int
isPythonFinalizing()
{
#if PY_VERSION_HEX >= 0x030D0000
    return Py_IsFinalizing();
#else
    return _Py_IsFinalizing();
#endif
}

inline bool
isEntryFrame(PyFrameObject* frame)
{
#if PY_VERSION_HEX >= 0x030B0000
    return _PyFrame_IsEntryFrame(frame);
#else
    (void)frame;
    return true;
#endif
}

inline PyFrameObject*
threadStateGetFrame(PyThreadState* tstate)
{
#if PY_VERSION_HEX < 0x030B0000
    // Prior to Python 3.11 this was exposed.
    return tstate->frame;
#else
    // Return a borrowed reference.
    PyFrameObject* ret = PyThreadState_GetFrame(tstate);
    if (ret) {
        assert(Py_REFCNT(ret) >= 2);
        Py_DECREF(ret);
    }
    return ret;
#endif
}

inline PyCodeObject*
frameGetCode(PyFrameObject* frame)
{
#if PY_VERSION_HEX < 0x030B0000
    // Prior to Python 3.11 this was exposed.
    return frame->f_code;
#else
    // Return a borrowed reference.
    PyCodeObject* ret = PyFrame_GetCode(frame);
    assert(Py_REFCNT(ret) >= 2);
    Py_DECREF(ret);
    return ret;
#endif
}

inline PyFrameObject*
frameGetBack(PyFrameObject* frame)
{
#if PY_VERSION_HEX < 0x030B0000
    // Prior to Python 3.11 this was exposed.
    return frame->f_back;
#else
    // Return a borrowed reference.
    PyFrameObject* ret = PyFrame_GetBack(frame);
    if (ret) {
        assert(Py_REFCNT(ret) >= 2);
        Py_DECREF(ret);
    }
    return ret;
#endif
}

inline int
frameGetLasti(PyFrameObject* frame)
{
#if PY_VERSION_HEX < 0x030B0000
    // Prior to Python 3.11 this was exposed.
    return frame->f_lasti;
#else
    // Use PyFrame_GetLasti for Python 3.11+
    return PyFrame_GetLasti(frame);
#endif
}

inline PyInterpreterState*
threadStateGetInterpreter(PyThreadState* tstate)
{
#if PY_VERSION_HEX < 0x03090000
    return tstate->interp;
#else
    return PyThreadState_GetInterpreter(tstate);
#endif
}

#if PY_VERSION_HEX >= 0x030E0000

extern "C" void
_PyEval_StopTheWorld(PyInterpreterState*);
extern "C" void
_PyEval_StartTheWorld(PyInterpreterState*);

inline void
stopTheWorld(PyInterpreterState* interp)
{
    _PyEval_StopTheWorld(interp);
}

inline void
startTheWorld(PyInterpreterState* interp)
{
    _PyEval_StartTheWorld(interp);
}

#else

inline void
stopTheWorld(PyInterpreterState*)
{
}

inline void
startTheWorld(PyInterpreterState*)
{
}

#endif

void
setprofileAllThreads(Py_tracefunc func, PyObject* arg);

inline PyObject*
codeGetLinetable(PyCodeObject* code)
{
#if PY_VERSION_HEX >= 0x030A0000
    // Python 3.10+ uses co_linetable
    return code->co_linetable;
#else
    // Python 3.9 and earlier use co_lnotab
    return code->co_lnotab;
#endif
}

inline const char*
codeGetLinetableBytes(PyCodeObject* code)
{
    PyObject* linetable = codeGetLinetable(code);
    if (linetable && PyBytes_Check(linetable)) {
        return PyBytes_AsString(linetable);
    }
    return nullptr;
}

inline Py_ssize_t
codeGetLinetableSize(PyCodeObject* code)
{
    PyObject* linetable = codeGetLinetable(code);
    if (linetable && PyBytes_Check(linetable)) {
        return PyBytes_Size(linetable);
    }
    return 0;
}

// Location information structure for line table parsing
struct LocationInfo
{
    int lineno;
    int end_lineno;
    int column;
    int end_column;
};

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
    const uint8_t* ptr = reinterpret_cast<const uint8_t*>(linetable.c_str());
    uint64_t addr = 0;
    info->lineno = firstlineno;

    auto scan_varint = [&]() {
        unsigned int read = *ptr++;
        unsigned int val = read & 63;
        unsigned int shift = 0;
        while (read & 64) {
            read = *ptr++;
            shift += 6;
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

    while (*ptr != '\0') {
        uint8_t first_byte = *(ptr++);
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
                info->column = *(ptr++);
                info->end_column = *(ptr++);
                break;
            }
            default: {
                uint8_t second_byte = *(ptr++);
                assert((second_byte & 128) == 0);
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
    int code_lineno = firstlineno;

    // Word-code is two bytes, so the actual limit in the table is 2 * the instruction index
    std::string::size_type last_executed_instruction = instruction_offset << 1;

    for (std::string::size_type i = 0, current_instruction = 0; i < linetable.size();) {
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
    int code_lineno = firstlineno;

    for (std::string::size_type i = 0, bc = 0; i < linetable.size();
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

// Unified parse function that uses compile-time version detection
inline bool
parseLinetable(const uintptr_t addrq, const std::string& linetable, int firstlineno, LocationInfo* info)
{
    if (linetable.empty()) {
        info->lineno = firstlineno;
        info->end_lineno = firstlineno;
        info->column = -1;
        info->end_column = -1;
        return true;
    }

#if PY_VERSION_HEX >= 0x030B0000
    // Python 3.11+ uses the new linetable format
    return parseLinetable311(addrq, linetable, firstlineno, info);
#elif PY_VERSION_HEX >= 0x030A0000
    // Python 3.10 uses a different format
    return parseLinetable310(addrq, linetable, firstlineno, info);
#else
    // Python 3.9 and earlier use co_lnotab format
    return parseLinetable39(addrq, linetable, firstlineno, info);
#endif
}

}  // namespace memray::compat
