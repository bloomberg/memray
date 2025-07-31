#pragma once

#include <atomic>
#include <thread>
#include <system_error>

namespace memray {

class SpinLock {
public:
    SpinLock() = default;
    ~SpinLock() = default;

    // Non-copyable and non-movable
    SpinLock(const SpinLock&) = delete;
    SpinLock& operator=(const SpinLock&) = delete;
    SpinLock(SpinLock&&) = delete;
    SpinLock& operator=(SpinLock&&) = delete;

    void lock() noexcept {
        // Use test-and-test-and-set pattern for better performance
        while (true) {
            // First test without acquiring the lock (read-only)
            while (locked_.load(std::memory_order_relaxed)) {
                // Hint to the processor that we're in a spin-wait loop
                __builtin_ia32_pause();
            }
            
            // Try to acquire the lock
            if (!locked_.exchange(true, std::memory_order_acquire)) {
                break;
            }
        }
    }

    bool try_lock() noexcept {
        // First check if already locked (avoid unnecessary atomic exchange)
        if (locked_.load(std::memory_order_relaxed)) {
            return false;
        }
        // Try to acquire
        return !locked_.exchange(true, std::memory_order_acquire);
    }

    void unlock() noexcept {
        locked_.store(false, std::memory_order_release);
    }

private:
    alignas(64) std::atomic<bool> locked_{false}; // Cache line aligned to avoid false sharing
};

// RAII lock guard for SpinLock (compatible with std::lock_guard interface)
template<typename Mutex>
class lock_guard {
public:
    using mutex_type = Mutex;

    explicit lock_guard(mutex_type& m) : mutex_(m) {
        mutex_.lock();
    }

    ~lock_guard() {
        mutex_.unlock();
    }

    // Non-copyable and non-movable
    lock_guard(const lock_guard&) = delete;
    lock_guard& operator=(const lock_guard&) = delete;

private:
    mutex_type& mutex_;
};

// RAII unique lock for SpinLock (compatible with std::unique_lock interface)
template<typename Mutex>
class unique_lock {
public:
    using mutex_type = Mutex;

    unique_lock() noexcept : mutex_(nullptr), owns_(false) {}

    explicit unique_lock(mutex_type& m) : mutex_(&m), owns_(false) {
        lock();
    }

    unique_lock(mutex_type& m, std::defer_lock_t) noexcept
        : mutex_(&m), owns_(false) {}

    unique_lock(mutex_type& m, std::try_to_lock_t)
        : mutex_(&m), owns_(mutex_->try_lock()) {}

    unique_lock(mutex_type& m, std::adopt_lock_t) noexcept
        : mutex_(&m), owns_(true) {}

    ~unique_lock() {
        if (owns_) {
            unlock();
        }
    }

    // Move constructor
    unique_lock(unique_lock&& other) noexcept
        : mutex_(other.mutex_), owns_(other.owns_) {
        other.mutex_ = nullptr;
        other.owns_ = false;
    }

    // Move assignment
    unique_lock& operator=(unique_lock&& other) noexcept {
        if (this != &other) {
            if (owns_) {
                unlock();
            }
            mutex_ = other.mutex_;
            owns_ = other.owns_;
            other.mutex_ = nullptr;
            other.owns_ = false;
        }
        return *this;
    }

    // Deleted copy operations
    unique_lock(const unique_lock&) = delete;
    unique_lock& operator=(const unique_lock&) = delete;

    void lock() {
        if (!mutex_) {
            throw std::system_error(std::make_error_code(std::errc::operation_not_permitted));
        }
        if (owns_) {
            throw std::system_error(std::make_error_code(std::errc::resource_deadlock_would_occur));
        }
        mutex_->lock();
        owns_ = true;
    }

    bool try_lock() {
        if (!mutex_) {
            throw std::system_error(std::make_error_code(std::errc::operation_not_permitted));
        }
        if (owns_) {
            throw std::system_error(std::make_error_code(std::errc::resource_deadlock_would_occur));
        }
        owns_ = mutex_->try_lock();
        return owns_;
    }

    void unlock() {
        if (!owns_) {
            throw std::system_error(std::make_error_code(std::errc::operation_not_permitted));
        }
        mutex_->unlock();
        owns_ = false;
    }

    // For std::condition_variable compatibility
    void swap(unique_lock& other) noexcept {
        std::swap(mutex_, other.mutex_);
        std::swap(owns_, other.owns_);
    }

    mutex_type* release() noexcept {
        mutex_type* ret = mutex_;
        mutex_ = nullptr;
        owns_ = false;
        return ret;
    }

    bool owns_lock() const noexcept {
        return owns_;
    }

    explicit operator bool() const noexcept {
        return owns_lock();
    }

    mutex_type* mutex() const noexcept {
        return mutex_;
    }

private:
    mutex_type* mutex_;
    bool owns_;
};

// scoped_lock for C++17 compatibility
template<typename Mutex>
class scoped_lock {
public:
    explicit scoped_lock(Mutex& m) : mutex_(m) {
        mutex_.lock();
    }

    ~scoped_lock() {
        mutex_.unlock();
    }

    // Non-copyable and non-movable
    scoped_lock(const scoped_lock&) = delete;
    scoped_lock& operator=(const scoped_lock&) = delete;

private:
    Mutex& mutex_;
};

} // namespace memray