import socket
import random
import struct

#>D:\Compiler\Acondana\python.exe D:\CS_homework\CS_net\net_work\UDPtask\Server.py 12345
# --- 协议定义 ---
# 使用 struct 来打包和解包协议头
# !: 网络字节序 (大端)
# I: 4字节无符号整数 (seq_num)
# I: 4字节无符号整数 (ack_num)
# H: 2字节无符号短整数 (flags)
# H: 2字节无符号短整数 (data_len)
HEADER_FORMAT = '!IIHH'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# 标志位定义
FLAG_SYN = 1 << 0  # 0001 (建立连接请求)
FLAG_ACK = 1 << 1  # 0010 (确认)
FLAG_FIN = 1 << 2  # 0100 (结束连接请求)
FLAG_DATA = 1 << 3  # 1000 (数据包)
# --- Server 配置 ---
LISTEN_IP = '0.0.0.0'  # 监听所有网络接口
LISTEN_PORT = 12345    # 默认端口号，可以通过命令行参数传入
PACKET_LOSS_RATE = 0.3 # 模拟丢包率，例如 0.3 表示有 30% 的概率丢弃数据包

def main():
    """
    服务器主函数
    """
    # 创建 UDP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind((LISTEN_IP, LISTEN_PORT))
    print(f"服务器已启动，正在监听 {LISTEN_IP}:{LISTEN_PORT}...")

    # GBN 服务器只维护一个期望序列号，代表当前期望收到的按序数据包的序列号
    expected_seq_num = 0
    # 记录当前连接的客户端地址，因为这是一个单连接服务器
    current_client_address = None

    print("\n--- 等待客户端连接 (SYN) ---")

    while True:
        try:
            # 接收数据，最大缓冲区 1024 字节
            packet, client_address = server_socket.recvfrom(1024)

            # 检查包的最小长度
            if len(packet) < HEADER_SIZE:
                print(f"收到来自 {client_address} 的不完整数据包，长度不足 ({len(packet)} < {HEADER_SIZE})，丢弃。")
                continue

            # 解包头部（先解包，以获取 flags 判断是否模拟丢包）
            seq_num, ack_num, flags, data_len = struct.unpack(HEADER_FORMAT, packet[:HEADER_SIZE])

            # --- 模拟随机丢包 (只对 DATA 包进行模拟丢弃) ---
            if (flags & FLAG_DATA) and random.random() < PACKET_LOSS_RATE:
                print(f"** 模拟丢包：丢弃了来自 {client_address} 的数据包 (Seq: {seq_num}) **")
                continue

            # 打印收到的包信息
            print(f"收到来自 {client_address} 的包 - Seq: {seq_num}, Ack: {ack_num}, Flags: {flags_to_str(flags)}, DataLen: {data_len}")

            # --- 处理不同类型的包 ---

            # 1. 处理 SYN 包 (模拟三次握手的第一步)
            if flags & FLAG_SYN:
                if current_client_address is not None and current_client_address != client_address:
                    print(f"已有连接 {current_client_address}，忽略来自 {client_address} 的新 SYN。")
                    continue # 忽略来自其他客户端的SYN，如果只支持一个连接

                print(f"收到来自 {client_address} 的 SYN 包，开始建立连接...")
                expected_seq_num = 0  # 收到 SYN，重置期望序列号为 0
                current_client_address = client_address # 记录当前连接的客户端

                # 回复 SYN-ACK
                # 服务器的序列号为 0，确认号为客户端的 seq_num + 1
                response_header = struct.pack(HEADER_FORMAT, 0, seq_num + 1, (FLAG_SYN | FLAG_ACK), 0)
                server_socket.sendto(response_header, client_address)
                print(f"已发送 SYN-ACK 到 {client_address} (Ack: {seq_num + 1})")

            # 2. 处理数据包 (DATA)
            elif flags & FLAG_DATA:
                # 检查是否是当前连接的客户端
                if current_client_address is None or current_client_address != client_address:
                    print(f"收到来自 {client_address} 的 DATA 包但无活跃连接或不是当前连接，忽略。")
                    continue

                # 检查序列号是否是期望的
                if seq_num == expected_seq_num:
                    data = packet[HEADER_SIZE:]
                    # print(f"收到期望的数据包 - Seq: {seq_num}, 数据: \"{data.decode('utf-8', errors='ignore')}\"") # 可选，打印数据内容
                    print(f"收到期望的数据包 - Seq: {seq_num}")

                    # 准备发送 ACK (确认号为收到的 seq_num，因为 GBN 累积确认)
                    ack_packet_header = struct.pack(HEADER_FORMAT, 0, seq_num, FLAG_ACK, 0)
                    server_socket.sendto(ack_packet_header, client_address)
                    print(f"已发送对 Seq {seq_num} 的 ACK")

                    # 更新期望的下一个序列号
                    expected_seq_num += 1
                else:
                    # GBN协议要求接收方丢弃所有失序的包，并重新确认最后一个按序收到的包
                    print(f"收到失序包！期望 Seq: {expected_seq_num}, 收到 Seq: {seq_num}。丢弃此包。")
                    # 重新发送对上一个正确包的 ACK (如果存在)
                    last_ack_num_to_send = expected_seq_num - 1
                    if last_ack_num_to_send >= 0:
                        ack_packet_header = struct.pack(HEADER_FORMAT, 0, last_ack_num_to_send, FLAG_ACK, 0)
                        server_socket.sendto(ack_packet_header, client_address)
                        print(f"重新发送对 Seq {last_ack_num_to_send} 的 ACK")
                    else:
                        print("没有已确认的包可重新发送 ACK。")

            # 3. 处理 ACK 包 (服务器通常不会收到客户端的 ACK，除非是连接关闭的ACK)
            elif flags & FLAG_ACK:
                # 在客户端进行完三次握手后，如果客户端发送 ACK，服务器可能会收到
                # 或者在四次挥手中，客户端收到服务器的FIN-ACK后，再给服务器发一个ACK
                print(f"收到 ACK 包 (Ack: {ack_num})")

            # 4. 处理 FIN 包 (客户端请求关闭连接)
            elif flags & FLAG_FIN:
                if current_client_address is None or current_client_address != client_address:
                    print(f"收到来自 {client_address} 的 FIN 包但无活跃连接或不是当前连接，忽略。")
                    continue

                print(f"收到来自 {client_address} 的 FIN 包 (Seq: {seq_num})，准备关闭连接。")
                # 回复 FIN-ACK (服务器的序列号为 0，确认号为客户端的 seq_num + 1)
                fin_ack_header = struct.pack(HEADER_FORMAT, 0, seq_num + 1, (FLAG_FIN | FLAG_ACK), 0)
                server_socket.sendto(fin_ack_header, client_address)
                print(f"已发送 FIN-ACK 到 {client_address} (Ack: {seq_num + 1})")

                # 重置状态以等待新连接（如果服务器设计为持续运行并接受新连接）
                expected_seq_num = 0
                current_client_address = None # 清除当前连接客户端信息
                print("服务器已完成当前连接的关闭，等待新的连接请求...")

            else:
                print(f"收到未知类型的包 (Flags: {flags})，丢弃。")

        except Exception as e:
            print(f"服务器出错: {e}")

def flags_to_str(flags):
    """辅助函数，将 flags 转换为可读字符串"""
    s = []
    if flags & FLAG_SYN: s.append("SYN")
    if flags & FLAG_ACK: s.append("ACK")
    if flags & FLAG_FIN: s.append("FIN")
    if flags & FLAG_DATA: s.append("DATA")
    if not s: s.append("NONE")
    return "|".join(s)

if __name__ == "__main__":
    # 可以通过命令行参数指定端口
    import sys
    if len(sys.argv) == 2:
        try:
            LISTEN_PORT = int(sys.argv[1])
        except ValueError:
            print("端口号必须是整数。")
            sys.exit(1)
    elif len(sys.argv) > 2:
        print(f"用法: python {sys.argv[0]} [端口号]")
        sys.exit(1)

    main()