#pragma once

#include <stdexcept>

namespace pensieve::exception {

class PensieveException : public std::runtime_error
{
    using std::runtime_error::runtime_error;
};

class IoError : public PensieveException
{
    using PensieveException::PensieveException;
};

}  // namespace pensieve::exception
