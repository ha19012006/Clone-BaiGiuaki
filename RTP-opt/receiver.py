import argparse
import socket
import sys

from utils import PacketHeader, compute_checksum

# Loại gói tin
START, END, DATA, ACK = 0, 1, 2, 3

HEADER_SIZE = 16


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


def receiver(receiver_ip, receiver_port, window_size):
    """Nhận gói, ghi message ra stdout theo đúng thứ tự (selective ACK)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if hasattr(socket, "SIO_UDP_CONNRESET"):  # chỉ có trên Windows
        try:
            sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except OSError:
            pass
    sock.bind((receiver_ip, receiver_port))
    out = sys.stdout.buffer

    connected = False
    expected = 0     # seq_num của gói DATA cần nhận tiếp theo
    buffer = {}      # gói đến sớm (lệch thứ tự) được giữ ở đây

    while True:
        try:
            raw, addr = sock.recvfrom(2048)
        except OSError:
            continue

        parsed = parse_packet(raw)
        if parsed is None:
            continue  # sai checksum -> bỏ, KHÔNG gửi ACK
        pkt_type, seq, data = parsed

        if pkt_type == START:
            if connected:
                continue  # đang có kết nối -> bỏ qua START
            connected = True
            expected = 1
            buffer = {}
            sock.sendto(make_packet(ACK, 1), addr)

        elif not connected:
            continue

        elif pkt_type == DATA:
            if seq >= expected + window_size:
                continue  # nằm ngoài cửa sổ -> bỏ, không ACK
            if seq >= expected:
                buffer[seq] = data
            # Ghi ra các gói liên tiếp bắt đầu từ `expected`
            while expected in buffer:
                out.write(buffer.pop(expected))
                expected += 1
            out.flush()
            # ACK riêng lẻ: trả về đúng seq_num của gói vừa nhận
            # (kể cả gói trùng lặp seq < expected, để sender biết gói đã đến)
            sock.sendto(make_packet(ACK, seq), addr)

        elif pkt_type == END:
            if seq != expected:
                continue  # END chỉ hợp lệ khi đã nhận hết dữ liệu
            out.flush()
            sock.sendto(make_packet(ACK, seq), addr)
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

    receiver(args.receiver_ip, args.receiver_port, args.window_size)


if __name__ == "__main__":
    main()
