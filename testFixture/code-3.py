--- NameError ---
print(undefined_variable) # 상세 분석(static)에서 탐지되어야 함
def scope_test():
    local_var = 10
print(local_var) # 함수 외부에서 접근 불가 (NameError)

--- ZeroDivisionError ---
x = 10 / 0 # 실시간(realtime) 및 상세(static)에서 탐지되어야 함
y = 5
z = 0
result = y / z # 상세(static)에서 탐지 시도 (추론 능력에 따라)

--- TypeError ---
num = 10
text = "hello"
combined = num + text # 상세(static)에서 탐지되어야 함
my_list = [1, 2]
combined_list = my_list + 5 # 상세(static)에서 탐지되어야 함

--- AttributeError ---
none_obj = None
print(none_obj.some_attribute) # 상세(static)에서 탐지되어야 함
class MySimpleClass:
    pass
obj = MySimpleClass()
print(obj.non_existent) # 상세(static)에서 탐지되어야 함

--- IndexError ---
data_list = [10, 20, 30]
print(data_list[3]) # 상세(static)에서 탐지되어야 함 (리터럴 인덱스)
print(data_list[-4]) # 상세(static)에서 탐지되어야 함 (리터럴 인덱스)
idx = 5
print(data_list[idx]) # 상세(static)에서 잠재적 경고 (구현 시)

--- KeyError ---
my_dictionary = {"a": 1, "b": 2}
print(my_dictionary["c"]) # 상세(static)에서 탐지되어야 함 (리터럴 키)
key_var = "d"
print(my_dictionary[key_var]) # 상세(static)에서 잠재적 경고 (구현 시)

--- InfiniteLoop ---
i = 0
while True: # 실시간(realtime) 및 상세(static)에서 탐지되어야 함
    print("Looping...")
    i += 1
    # break 없음

--- RecursionError ---
def recursive_hello():
    print("Hello again!")
    recursive_hello() # 실시간(realtime) 및 상세(static)에서 탐지되어야 함
recursive_hello()

--- FileNotFoundError ---
상세(static)에서 탐지되어야 함 (파일이 실제로 없어야 함)
try:
    f = open("non_existent_file.txt", "r")
    f.close()
except FileNotFoundError:
    pass # 실제 실행 시에는 오류 안 나지만, 정적 분석 시 탐지 가능

--- 정상 코드 ---
def greet(name):
    message = f"Hello, {name}!"
    print(message)
    return len(message)

length = greet("World")
print(f"Length of greeting: {length}")