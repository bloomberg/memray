import numpy as np

# DO NOT CHANGE
MB_CONVERSION = 1024 * 1024
DUPLICATE_CONST = 2

SIZE_OF_DATA_IN_MB = 100
SUBTRACT_AMOUNT = 3
POWER_AMOUNT = 2
ADD_AMOUNT = 10
# DO NOT CHANGE


def load_xMb_of_data(mb: int) -> np.ndarray:
    size = MB_CONVERSION * mb  # DO NOT CHANGE
    return np.ones(size, dtype=np.uint8)


def duplicate_data(data: np.ndarray) -> np.ndarray:
    return data * DUPLICATE_CONST


def add_scalar(data: np.ndarray, scalar: int) -> np.ndarray:
    return data + scalar


def subtract_scalar(data: np.ndarray, scalar: int) -> np.ndarray:
    return data - scalar


def raise_to_power(data: np.ndarray, power: int) -> np.ndarray:
    return np.power(data, power)


def process_data() -> np.ndarray:
    data = load_xMb_of_data(SIZE_OF_DATA_IN_MB)
    data = subtract_scalar(data, SUBTRACT_AMOUNT)
    data_pow = raise_to_power(data, POWER_AMOUNT)
    return add_scalar(duplicate_data(data_pow), ADD_AMOUNT)


if __name__ == "__main__":
    process_data()
