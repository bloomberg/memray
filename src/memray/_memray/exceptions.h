#pragma once

#include <stdexcept>

namespace memray::exception {

class PensieveException : public std::runtime_error
{
    using std::runtime_error::runtime_error;
};

class IoError : public PensieveException
{
    using PensieveException::PensieveException;
};

}  // namespace memray::exception
