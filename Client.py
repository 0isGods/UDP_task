import socket
import struct
import time
import sys
import pandas as pd  # 用于统计

#D:\Compiler\Acondana\python.exe D:\CS_homework\CS_net\net_work\UDPtask\Client.py "127.0.0.1" 12345

# --- 协议定义 (与服务器端一致) ---
HEADER_FORMAT = '!IIHH'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
FLAG_SYN = 1 << 0
FLAG_ACK = 1 << 1
FLAG_FIN = 1 << 2
FLAG_DATA = 1 << 3

# --- Client 配置 ---
# 从命令行获取服务器 IP 和端口
if len(sys.argv) != 3:
    print(f"用法: python {sys.argv[0]} <server_ip> <server_port>")
    sys.exit(1)

SERVER_IP = sys.argv[1]
SERVER_PORT = int(sys.argv[2])

TIMEOUT = 0.3  # 超时时间 300ms
WINDOW_SIZE = 5  # GBN 的发送窗口大小 (以数据包数量计)
PACKET_DATA_SIZE = 80  # 每个数据包的实际数据负载大小 (字节)
TOTAL_DATA_BYTES = 3000  # 总数据量，例如 3000 字节

# --- 全局变量和状态 ---
client_socket = None
send_buffer = {}  # 存储 (seq_num: (packet_bytes, send_timestamp))
rtt_records = []  # 记录所有成功测量的 RTT
total_packets_sent_attempts = 0  # 统计所有发送尝试次数（包括重传）
unique_packets_acked = set()  # 记录成功确认的唯一数据包序列号


def create_packet(seq_num, ack_num, flags, data=b''):
    """创建数据包"""
    data_len = len(data)
    header = struct.pack(HEADER_FORMAT, seq_num, ack_num, flags, data_len)
    return header + data


def calculate_byte_range(seq_num, data_len):
    """根据序列号和数据长度计算字节范围字符串。"""
    start_byte = seq_num * PACKET_DATA_SIZE
    end_byte = start_byte + data_len - 1
    return f"{start_byte}~{end_byte}"


def send_data_packet(packet_seq_num, packet_data, server_addr):
    """发送一个数据包并更新发送尝试次数和发送时间戳。"""
    global total_packets_sent_attempts, send_buffer

    packet_bytes = create_packet(packet_seq_num, 0, FLAG_DATA, packet_data)
    client_socket.sendto(packet_bytes, server_addr)
    total_packets_sent_attempts += 1

    # 如果是第一次发送此包，记录其发送时间
    # 如果是重传，保持第一次的发送时间，以便计算准确的RTT

    send_buffer[packet_seq_num] = (packet_bytes, time.time())
    # else: 已经在send_buffer中，保留原始发送时间

    byte_range_str = calculate_byte_range(packet_seq_num, len(packet_data))
    print(f"发送第 {packet_seq_num} 个 (字节 {byte_range_str}) 数据包...")


def main():
    global client_socket, send_buffer, total_packets_sent_attempts, unique_packets_acked

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.settimeout(TIMEOUT)  # 设置 socket 接收超时

    server_addr = (SERVER_IP, SERVER_PORT)

    # --- 1. 模拟三次握手 ---
    print("--- 开始三次握手 ---")
    syn_seq_num = 100  # 握手阶段使用独立的序列号
    syn_packet = create_packet(syn_seq_num, 0, FLAG_SYN)

    handshake_success = False
    for _ in range(5):  # 最多重试5次
        try:
            print("发送 SYN...")
            client_socket.sendto(syn_packet, server_addr)
            response, _ = client_socket.recvfrom(1024)
            header = struct.unpack(HEADER_FORMAT, response[:HEADER_SIZE])

            # 检查是否是 SYN-ACK 并且 ack num 正确，且服务器的 ack_num 确认了我们的 syn_seq_num + 1
            if (header[2] & FLAG_SYN) and (header[2] & FLAG_ACK) and header[1] == syn_seq_num + 1:
                print("收到 SYN-ACK。")

                # **关键修改：发送三次握手的最后一个 ACK**
                # 客户端的 ACK 序列号通常是它发送的 SYN 序列号 + 1
                # 客户端的 ACK 确认号是服务器 SYN-ACK 的序列号 + 1 (这里服务器 SYN-ACK 序列号是 0，所以是 0 + 1 = 1)
                # 但更标准的做法是确认服务器的 SYN-ACK 序列号+1。
                # 这里的 server_ack_seq_num 是服务器的 ack_num (即 syn_seq_num + 1), 但这是服务器对我们seq的ack，不是它自己的seq。
                # 因为服务器的 SYN-ACK 包的 seq_num 是 0，所以客户端的 ACK 的 ack_num 应该是 0 + 1 = 1
                # 为了与服务器代码保持一致（服务器在SYN-ACK中seq_num为0），这里确认0+1
                final_ack_packet = create_packet(syn_seq_num + 1, header[0] + 1, FLAG_ACK) # 客户端Seq=101, Ack=0+1=1
                client_socket.sendto(final_ack_packet, server_addr)
                print(f"发送 ACK (Seq: {syn_seq_num + 1}, Ack: {header[0] + 1}) 完成三次握手！")

                handshake_success = True
                break
        except socket.timeout:
            print("SYN 请求超时，正在重试...")
        except Exception as e:
            print(f"握手过程中发生错误: {e}")
            break

    if not handshake_success:
        print("三次握手失败，客户端退出。")
        client_socket.close()
        sys.exit(1)

    print("--- 三次握手完成 ---\n")

    # --- 2. 准备并发送数据 ---
    # 根据要求，将一个 TOTAL_DATA_BYTES 字节的数据拆分
    message = b'A' * TOTAL_DATA_BYTES
    packets_to_send_data = []  # 存储每个数据包的实际数据内容
    for i in range(0, len(message), PACKET_DATA_SIZE):
        chunk = message[i:i + PACKET_DATA_SIZE]
        packets_to_send_data.append(chunk)

    num_packets = len(packets_to_send_data)
    print(f"总数据大小: {len(message)} 字节, 将拆分为 {num_packets} 个包发送。")

    base = 0  # GBN 窗口的基部 (指向发送但未确认的最小序列号)
    next_seq_num = 0  # 下一个要发送的包的序列号

    last_ack_receipt_time = time.time()  # 记录上次收到有效ACK的时间，用于判断超时

    while base < num_packets:
        # --- 发送窗口内所有可用的新包 ---
        # next_seq_num < base + WINDOW_SIZE: 窗口未满
        # next_seq_num < num_packets: 还有数据要发送
        while next_seq_num < base + WINDOW_SIZE and next_seq_num < num_packets:
            send_data_packet(next_seq_num, packets_to_send_data[next_seq_num], server_addr)
            next_seq_num += 1
            # 启动计时器 (Go-Back-N 只为 base 包计时)
            if base == next_seq_num - 1:  # 如果刚发送的是 base 包
                last_ack_receipt_time = time.time()

        # --- 检查是否超时，并重传 ---
        # base < num_packets: 还有未确认的包
        # time.time() - last_ack_receipt_time > TIMEOUT: base 包超时
        if base < num_packets and (time.time() - last_ack_receipt_time > TIMEOUT):
            print(f"发生超时 (超时时间 {TIMEOUT * 1000}ms)，未收到 base 包 {base} 的回复。")
            print("--- 开始重传 ---")
            # GBN: 超时，重传从 base 开始到 next_seq_num - 1 的所有已发送但未确认的包
            for i in range(base, next_seq_num):
                # 从 send_buffer 中获取原始包数据
                packet_bytes_original, _ = send_buffer[i]  # 取得原字节串

                # 因为 packet_bytes_original 已经是 create_packet 的结果
                # 可以直接发送，但为了打印日志，我们重新获取数据和序号
                # 注意：这里直接用 send_buffer[i][0] 而不是 packets_to_send_data[i]
                # 是为了在实际项目中，可以确保重传的是缓冲区里的包，而不是重新从原始数据构造

                # 重新构建包信息用于日志
                _, _, _, data_len_retransmit = struct.unpack(HEADER_FORMAT, packet_bytes_original[:HEADER_SIZE])
                byte_range_str = calculate_byte_range(i, data_len_retransmit)

                client_socket.sendto(packet_bytes_original, server_addr)
                send_buffer[i] = (packet_bytes_original, time.time())
                total_packets_sent_attempts += 1
                print(f"重传第 {i} 个 (字节 {byte_range_str}) 数据包。")

            last_ack_receipt_time = time.time()  # 重传后重新启动计时器
            print("--- 重传结束 ---\n")

        # --- 尝试接收 ACK ---
        try:
            response, _ = client_socket.recvfrom(1024)
            header = struct.unpack(HEADER_FORMAT, response[:HEADER_SIZE])
            ack_num = header[1]
            flags = header[2]

            if flags & FLAG_ACK:
                # GBN 是累积确认，收到 ack_num 表示 ack_num 及之前的所有包都已收到
                if ack_num >= base:  # 确保 ACK 是新的或有效的
                    # 遍历所有被确认的包，计算 RTT 并更新 base
                    for i in range(base, ack_num + 1):
                        if i in send_buffer:  # 确保这个包在我们的发送缓冲区中
                            _, sent_time = send_buffer[i]
                            rtt = (time.time() - sent_time) * 1000  # 转换为毫秒
                            rtt_records.append(rtt)

                            # 打印 ACK 信息，包括 RTT
                            # 只有第一次确认才打印 "server 端已经收到"
                            if i not in unique_packets_acked:
                                byte_range_str = calculate_byte_range(i, PACKET_DATA_SIZE)
                                print(f"收到第 {i} 个 ({byte_range_str}) server 端已经收到, RTT 是 {rtt:.2f} ms")
                                unique_packets_acked.add(i)

                            del send_buffer[i]  # 从缓冲区移除已确认的包

                    base = ack_num + 1  # 移动窗口基准
                    last_ack_receipt_time = time.time()  # 收到新 ACK，重置计时器
                # else: print(f"收到旧的或重复的ACK: {ack_num}") # 可选：调试信息
            # else: print(f"收到非 ACK 包，flags: {flags}") # 可选：调试信息

        except socket.timeout:
            # print("等待 ACK 超时。") # 此处不打印，交给上面的超时逻辑统一处理
            pass  # 继续循环，由上面的计时器检测并触发重传
        except Exception as e:
            print(f"接收数据时发生错误: {e}")
            break  # 退出循环

    print("\n--- 所有数据包均已确认 ---")

    # --- 3. 四次挥手 (假设客户端先发起 FIN) ---
    print("\n--- 开始四次挥手 ---")
    fin_seq_num = next_seq_num  # FIN包的序列号可以从当前next_seq_num开始
    fin_packet = create_packet(fin_seq_num, 0, FLAG_FIN)

    fin_ack_received = False
    for _ in range(5):  # 最多重试5次
        try:
            client_socket.sendto(fin_packet, server_addr)
            print("已发送 FIN 包。")
            response, _ = client_socket.recvfrom(1024)
            header = struct.unpack(HEADER_FORMAT, response[:HEADER_SIZE])
            # 服务器的FIN-ACK通常会确认客户端的FIN包，所以它的ack_num应该是fin_seq_num + 1
            if (header[2] & FLAG_FIN) and (header[2] & FLAG_ACK) and header[1] == fin_seq_num + 1:
                print("收到 FIN-ACK，连接已关闭。")
                fin_ack_received = True
                break
        except socket.timeout:
            print("等待 FIN-ACK 超时，正在重试...")
        except Exception as e:
            print(f"关闭连接时发生错误: {e}")
            break

    if not fin_ack_received:
        print("未收到 FIN-ACK，但仍认为连接已关闭 (超时)。")

    # --- 4. 统计信息 ---
    print("\n--- 【汇总】信息 ---")

    # 计算丢包率 (更精确的计算)
    # total_packets_sent_attempts 在每次调用 client_socket.sendto() 时递增
    # len(unique_packets_acked) 是唯一成功确认的原始数据包数量

    if total_packets_sent_attempts > 0:
        actual_loss_count = total_packets_sent_attempts - len(unique_packets_acked)
        loss_rate = (len(unique_packets_acked) / total_packets_sent_attempts) * 100
        print(f"● 数据包发送尝试总数 (含重传): {total_packets_sent_attempts}")
        print(f"● 成功确认的唯一数据包数量: {len(unique_packets_acked)}")
        print(f"● 估算重传次数 (或未确认的发送尝试): {actual_loss_count}")
        print(f"● 丢包率: {loss_rate:.2f}%")
    else:
        print("● 没有发送任何数据包，无法计算丢包率。")

    # 计算 RTT 统计
    if rtt_records:
        rtt_series = pd.Series(rtt_records)
        print(f"● 最大 RTT: {rtt_series.max():.2f} ms")
        print(f"● 最小 RTT: {rtt_series.min():.2f} ms")
        print(f"● 平均 RTT: {rtt_series.mean():.2f} ms")
        print(f"● RTT 标准差: {rtt_series.std():.2f} ms")
    else:
        print("● 没有有效的 RTT 记录。")

    client_socket.close()
    print("客户端已关闭。")


if __name__ == "__main__":
    main()