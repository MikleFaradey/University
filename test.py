import socket

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect(("localhost", 8087))
message = "GaGask"
client_socket.send(message.encode())
data = client_socket.recv(1024).decode()
print(f"Ans is {data}")
client_socket.close()