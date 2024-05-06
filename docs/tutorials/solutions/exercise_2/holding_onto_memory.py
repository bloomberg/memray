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
    size = MB_CONVERSION * mb
    return np.ones(size, dtype=np.uint8)


def duplicate_data(data: np.ndarray) -> np.ndarray:
    return data * DUPLICATE_CONST


def add_scalar(data: np.ndarray, scalar: int) -> np.ndarray:
    return data + scalar


def subtract_scalar(data: np.ndarray, scalar: int) -> np.ndarray:
    return data - scalar


def raise_to_power(data: np.ndarray, power: int) -> np.ndarray:
    return np.power(data, power)


def process_data_fix_1():
    # no extra reference to the original array
    return add_scalar(
        duplicate_data(
            raise_to_power(
                subtract_scalar(load_xMb_of_data(SIZE_OF_DATA_IN_MB), SUBTRACT_AMOUNT),
                POWER_AMOUNT,
            )
        ),
        ADD_AMOUNT,
    )


def process_data_fix_2():
    # reusing the local variable instead of allocating more space
    # this approach is called 'hidden mutability'
    data = load_xMb_of_data(SIZE_OF_DATA_IN_MB)
    data = subtract_scalar(data, SUBTRACT_AMOUNT)
    data = raise_to_power(data, POWER_AMOUNT)
    data = duplicate_data(data)
    data = add_scalar(data, ADD_AMOUNT)
    return data


# Use these to select which solution to test
process_data = process_data_fix_1

if __name__ == "__main__":
    process_data()
