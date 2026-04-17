import 'dart:convert';
import 'package:http/http.dart' as http;

class Target {
  final int x;
  final int y;
  final int area;
  Target(this.x, this.y, this.area);

  factory Target.fromJson(Map<String, dynamic> j) =>
      Target(j['x'] as int, j['y'] as int, j['area'] as int);
}

class PidInfo {
  final double error, p, i, d, turn, fwd;
  PidInfo(this.error, this.p, this.i, this.d, this.turn, this.fwd);

  factory PidInfo.fromJson(Map<String, dynamic> j) => PidInfo(
        (j['error'] as num?)?.toDouble() ?? 0,
        (j['p'] as num?)?.toDouble() ?? 0,
        (j['i'] as num?)?.toDouble() ?? 0,
        (j['d'] as num?)?.toDouble() ?? 0,
        (j['turn'] as num?)?.toDouble() ?? 0,
        (j['fwd'] as num?)?.toDouble() ?? 0,
      );
}

class BrainStatus {
  final String mode;
  final String color;
  final Target? target;
  final double fps;
  final bool running;
  final int? frameW;
  final int? frameH;
  final String searchState;
  final PidInfo? pid;
  final int? rssi;
  final double? obstacleDist;
  final bool obstacleCam;
  final String shadowState;
  final Map<String, dynamic>? intel;
  final String? streamUrl;

  BrainStatus({
    required this.mode,
    required this.color,
    required this.target,
    required this.fps,
    required this.running,
    this.frameW,
    this.frameH,
    this.searchState = 'idle',
    this.pid,
    this.rssi,
    this.obstacleDist,
    this.obstacleCam = false,
    this.shadowState = 'idle',
    this.intel,
    this.streamUrl,
  });

  factory BrainStatus.fromJson(Map<String, dynamic> j) => BrainStatus(
        mode: j['mode'] as String? ?? 'manual',
        color: j['color'] as String? ?? 'red',
        target: j['target'] == null
            ? null
            : Target.fromJson(j['target'] as Map<String, dynamic>),
        fps: ((j['fps'] as num?) ?? 0).toDouble(),
        running: j['running'] as bool? ?? false,
        frameW: j['frame_w'] as int?,
        frameH: j['frame_h'] as int?,
        searchState: j['search_state'] as String? ?? 'idle',
        pid: j['pid'] == null
            ? null
            : PidInfo.fromJson(j['pid'] as Map<String, dynamic>),
        rssi: j['rssi'] as int?,
        obstacleDist: (j['obstacle_dist'] as num?)?.toDouble(),
        obstacleCam: j['obstacle_cam'] as bool? ?? false,
        shadowState: j['shadow_state'] as String? ?? 'idle',
        intel: j['intel'] as Map<String, dynamic>?,
        streamUrl: j['stream_url'] as String?,
      );
}

class BrainApi {
  final String baseUrl;
  final http.Client _client = http.Client();
  BrainApi(this.baseUrl);

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  Future<BrainStatus> status() async {
    final r = await _client.get(_u('/status')).timeout(const Duration(seconds: 2));
    return BrainStatus.fromJson(jsonDecode(r.body) as Map<String, dynamic>);
  }

  Future<void> setMode(String mode) async {
    await _client.post(
      _u('/mode'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({'mode': mode}),
    );
  }

  Future<void> setColor(String preset) async {
    await _client.post(
      _u('/color'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({'preset': preset}),
    );
  }

  Future<void> drive(int l, int r) async {
    await _client.post(
      _u('/drive'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({'l': l, 'r': r}),
    );
  }

  Future<void> stop() async {
    await _client.post(_u('/stop'));
  }

  Future<void> selectTarget({int? index, int? x, int? y}) async {
    await _client.post(
      _u('/select_target'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode({'index': index, 'x': x, 'y': y}),
    );
  }

  Future<Map<String, dynamic>> getTune() async {
    final r = await _client.get(_u('/tune')).timeout(const Duration(seconds: 2));
    return jsonDecode(r.body) as Map<String, dynamic>;
  }

  Future<void> setTune(Map<String, dynamic> params) async {
    await _client.post(
      _u('/tune'),
      headers: const {'Content-Type': 'application/json'},
      body: jsonEncode(params),
    );
  }
}
