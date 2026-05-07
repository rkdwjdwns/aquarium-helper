"""
camera_stream.py
Raspberry Pi 카메라 MJPEG 스트리밍 서버

실행: python camera_stream.py
접속: http://[Pi IP]:8080/stream.mjpg

브라우저 또는 dashboard camera.html에서 스트림 수신
"""

import io
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

try:
    from picamera2 import Picamera2
    USE_PICAMERA = True
except ImportError:
    import cv2
    USE_PICAMERA = False
    print("[STREAM] picamera2 없음 → OpenCV 카메라 사용")

# ── 설정 ──────────────────────────────────────
HOST        = '0.0.0.0'
PORT        = 8080
RESOLUTION  = (640, 480)
FRAMERATE   = 30
JPEG_QUALITY = 85


class StreamHandler(BaseHTTPRequestHandler):
    """MJPEG 스트리밍 HTTP 핸들러"""

    def log_message(self, format, *args):
        pass   # 콘솔 로그 억제

    def do_GET(self):
        path = self.path.split('?')[0]  # 쿼리 파라미터 제거
        if path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()

            try:
                while True:
                    frame = self.server.get_frame()
                    if frame is None:
                        time.sleep(0.033)
                        continue

                    self.wfile.write(b'--frame\r\n')
                    self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')

            except (BrokenPipeError, ConnectionResetError):
                pass   # 클라이언트 연결 끊김

        elif path == '/snapshot.jpg':
            frame = self.server.get_frame()
            if frame:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(frame)
            else:
                self.send_response(503)
                self.end_headers()

        elif path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'ok')

        else:
            self.send_response(404)
            self.end_headers()


class CameraServer(HTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._frame      = None
        self._frame_lock = threading.Lock()
        self._camera     = None
        self._start_camera()

    def get_frame(self) -> bytes | None:
        with self._frame_lock:
            return self._frame

    def _set_frame(self, frame: bytes):
        with self._frame_lock:
            self._frame = frame

    def _start_camera(self):
        """카메라 캡처 스레드 시작"""
        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()

    def _capture_loop(self):
        if USE_PICAMERA:
            self._capture_picamera()
        else:
            self._capture_opencv()

    def _capture_picamera(self):
        """picamera2 캡처 루프"""
        import numpy as np
        import cv2 as cv

        cam = Picamera2()
        config = cam.create_video_configuration(
            main={"size": RESOLUTION, "format": "RGB888"}
        )
        cam.configure(config)
        cam.start()
        print(f"[STREAM] picamera2 시작 {RESOLUTION[0]}x{RESOLUTION[1]}")

        try:
            while True:
                frame = cam.capture_array()
                _, buf = cv.imencode(
                    '.jpg', frame,
                    [cv.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                )
                self._set_frame(buf.tobytes())
                time.sleep(1.0 / FRAMERATE)
        finally:
            cam.stop()

    def _capture_opencv(self):
        """OpenCV 캡처 루프 (USB 카메라 또는 테스트용)"""
        import cv2 as cv

        cap = cv.VideoCapture(0)
        cap.set(cv.CAP_PROP_FRAME_WIDTH,  RESOLUTION[0])
        cap.set(cv.CAP_PROP_FRAME_HEIGHT, RESOLUTION[1])
        cap.set(cv.CAP_PROP_FPS,          FRAMERATE)
        print(f"[STREAM] OpenCV 카메라 시작 {RESOLUTION[0]}x{RESOLUTION[1]}")

        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            _, buf = cv.imencode(
                '.jpg', frame,
                [cv.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
            )
            self._set_frame(buf.tobytes())
            time.sleep(1.0 / FRAMERATE)


# ──────────────────────────────────────────────
# 서버 실행
# ──────────────────────────────────────────────

if __name__ == '__main__':
    server = CameraServer((HOST, PORT), StreamHandler)
    print(f"[STREAM] 스트리밍 서버 시작")
    print(f"[STREAM] 스트림 URL: http://[Pi IP]:{PORT}/stream.mjpg")
    print(f"[STREAM] 스냅샷 URL: http://[Pi IP]:{PORT}/snapshot.jpg")
    print(f"[STREAM] 종료: Ctrl+C")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[STREAM] 서버 종료")
        server.shutdown()