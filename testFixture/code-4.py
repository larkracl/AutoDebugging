# 여러 함수, 클래스, 모듈을 포함하는 복잡한 코드

class MyClass:
    def __init__(self, value):
        self.value = value

    def divide_by(self, divisor):
        return self.value / divisor  # ZeroDivisionError 발생 가능

def my_function(a, b):
    if b == 0:
        return "Cannot divide by zero"  # ZeroDivisionError 회피
    else:
        return a / b

obj = MyClass(10)
# result1 = obj.divide_by(0)  # ZeroDivisionError
result2 = my_function(5, 2)

import math  # 모듈 import

def calculate_sqrt(x):
    if x < 0:
       print(error_message) # NameError
    return math.sqrt(x)

calculate_sqrt(4)

def time:
    ㅇㅈㅇㅈㅇㅈ
    ㅂㅇㅈㅇㅈㅇ
    ㅇㅈㅇㅈd