import argparse
import select
import socket
import sys
import time

from utils import PacketHeader, compute_checksum

# Loại gói tin
START, END, DATA, ACK = 0, 1, 2, 3

HEADER_SIZE = 16                       # 4 trường int x 4 byte
MAX_PACKET = 1472                      # 1500 - 20 (IP) - 8 (UDP)
MAX_DATA = MAX_PACKET - HEADER_SIZE    # 1456 byte dữ liệu mỗi gói
TIMEOUT = 0.5                          # 500 ms


def make_packet(pkt_type, seq_num, data=b""):
    """Đóng gói header + data, checksum tính khi trường checksum = 0."""
    header = PacketHeader(type=pkt_type, seq_num=seq_num, length=len(data))
    header.checksum = 0
    header.checksum = compute_checksum(header / data)
    return bytes(header / data)


def parse_packet(raw):
    """Trả về (type, seq_num, data), hoặc None nếu gói bị hỏng."""
    if len(raw) < HEADER_SIZE:
        return None
    header = PacketHeader(raw[:HEADER_SIZE])
    data = raw[HEADER_SIZE:HEADER_SIZE + header.length]
    if len(data) != header.length:
        return None
    recv_checksum = header.checksum
    header.checksum = 0
    if compute_checksum(header / data) != recv_checksum:
        return None
    return header.type, header.seq_num, data


def recv_ack(sock, timeout):
    """Chờ tối đa `timeout` giây một gói ACK hợp lệ. Trả về seq_num hoặc None."""
    if timeout <= 0:
        return None
    ready, _, _ = select.select([sock], [], [], timeout)
    if not ready:
        return None
    try:
        raw, _ = sock.recvfrom(2048)
    except OSError:  # Windows đôi khi báo lỗi ConnectionReset với UDP
        return None
    parsed = parse_packet(raw)
    if parsed is None or parsed[0] != ACK:
        return None
    return parsed[1]


def sender(receiver_ip, receiver_port, window_size):
    """Đọc message từ stdin và gửi bằng RTP (cửa sổ trượt + selective ACK)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if hasattr(socket, "SIO_UDP_CONNRESET"):  # chỉ có trên Windows
        try:
            sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except OSError:
            pass
    addr = (receiver_ip, receiver_port)

    # 1. Cắt message thành các gói DATA, chunk thứ i có seq_num = i + 1
    message = sys.stdin.buffer.read()
    chunks = [message[i:i + MAX_DATA] for i in range(0, len(message), MAX_DATA)]
    packets = [make_packet(DATA, i + 1, c) for i, c in enumerate(chunks)]
    n = len(packets)

    # 2. Bắt tay: gửi START (seq 0), chờ ACK có seq 1
    while True:
        sock.sendto(make_packet(START, 0), addr)
        deadline = time.time() + TIMEOUT
        got_ack = False
        while time.time() < deadline:
            if recv_ack(sock, deadline - time.time()) == 1:
                got_ack = True
                break
        if got_ack:
            break

    # 3. Truyền dữ liệu bằng cửa sổ trượt + selective ACK
    base = 1        # gói cũ nhất chưa được ACK
    next_seq = 1    # gói tiếp theo sẽ gửi
    acked = set()   # các seq trong cửa sổ đã được ACK riêng lẻ
    timer_start = time.time()

    while base <= n:
        # Gửi thêm các gói còn nằm trong cửa sổ
        while next_seq < base + window_size and next_seq <= n:
            sock.sendto(packets[next_seq - 1], addr)
            next_seq += 1

        remaining = TIMEOUT - (time.time() - timer_start)
        if remaining <= 0:
            # Hết 500ms (một timer chung): chỉ gửi lại các gói CHƯA được ACK
            for seq in range(base, next_seq):
                if seq not in acked:
                    sock.sendto(packets[seq - 1], addr)
            timer_start = time.time()
            continue

        ack = recv_ack(sock, remaining)
        # ACK riêng lẻ: ack chính là seq_num của gói DATA đã nhận
        if ack is not None and base <= ack < next_seq:
            acked.add(ack)
            old_base = base
            while base in acked:  # trượt cửa sổ qua các gói đã ACK liên tiếp
                acked.discard(base)
                base += 1
            if base > old_base:
                timer_start = time.time()  # cửa sổ dịch -> reset timer

    # 4. Kết thúc: gửi END (seq n + 1), chờ ACK (seq n + 1) tối đa 500ms
    sock.sendto(make_packet(END, n + 1), addr)
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        ack = recv_ack(sock, deadline - time.time())
        if ack == n + 1:
            break
    sock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "receiver_ip", help="The IP address of the host that receiver is running on"
    )
    parser.add_argument(
        "receiver_port", type=int, help="The port number on which receiver is listening"
    )
    parser.add_argument(
        "window_size", type=int, help="Maximum number of outstanding packets"
    )
    args = parser.parse_args()

    sender(args.receiver_ip, args.receiver_port, args.window_size)


if __name__ == "__main__":
    main()
