# test.py
# ZeroDivisionError
print(10 / 0)

# NameError
print(undefined_variable)

# TypeError
print(10 + "abc")

# AttributeError
x = None
# print(x.attribute) # 주석 해제 시 실시간

# IndexError
my_list = [1, 2, 3]
# print(my_list[10]) # 주석 해제 시 실시간

# KeyError
my_dict = {"a": 1, "b": 2}
# print(my_dict["c"])  # 주석 해제시 실시간

# 무한 루프
# while True: # 주석 해제 시 실시간
#     pass

# Recursion Error
def recursive_func():
    recursive_func()
# recursive_func() # 주석 해제 시 실행

# 정상 코드
def normal_func():
    y = 10
    print(y)
normal_func()

def divide(a,b):
    return a/b
print(divide(10, 2))

def print(111):