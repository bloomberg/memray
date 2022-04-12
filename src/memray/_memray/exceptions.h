#pragma once

#include <stdexcept>

namespace memray::exception {

class MemrayException : public std::runtime_error
{
    using std::runtime_error::runtime_error;
};

class IoError : public MemrayException
{
    using MemrayException::MemrayException;
};

}  // namespace memray::exception
