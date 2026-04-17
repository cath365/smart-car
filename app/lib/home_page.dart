import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_joystick/flutter_joystick.dart';
import 'package:flutter_mjpeg/flutter_mjpeg.dart';

import 'api.dart';

const _colorPresets = ['red', 'red2', 'green', 'blue', 'yellow'];
const _modes = ['manual', 'color', 'person', 'shadow'];

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  final _brainCtrl  = TextEditingController(text: 'http://192.168.1.100:8000');
  final _streamCtrl = TextEditingController();
  bool _streamAutoSet = false;

  BrainApi? _api;
  BrainStatus? _status;
  Timer? _pollTimer;
  Timer? _driveTimer;
  double _joyX = 0, _joyY = 0;

  @override
  void initState() {
    super.initState();
    // Auto-connect on launch
    Future.delayed(const Duration(milliseconds: 300), _connect);
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _driveTimer?.cancel();
    super.dispose();
  }

  void _connect() {
    _api = BrainApi(_brainCtrl.text.trim());
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(milliseconds: 400), (_) async {
      try {
        final s = await _api!.status();
        if (mounted) {
          // Auto-load camera stream from brain
          if (s.streamUrl != null && s.streamUrl!.isNotEmpty && !_streamAutoSet) {
            _streamCtrl.text = s.streamUrl!;
            _streamAutoSet = true;
          }
          setState(() => _status = s);
        }
      } catch (_) {
        if (mounted) setState(() => _status = null);
      }
    });
    _driveTimer?.cancel();
    _driveTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      final api = _api;
      if (api == null) return;
      if ((_status?.mode ?? 'manual') != 'manual') return;
      // Differential drive mixing: y=forward/back, x=turn.
      final forward = (-_joyY * 200).toInt();
      final turn    = (_joyX * 180).toInt();
      final l = (forward + turn).clamp(-255, 255);
      final r = (forward - turn).clamp(-255, 255);
      api.drive(l, r);
    });
    setState(() {});
  }

  Future<void> _setMode(String m) async {
    await _api?.setMode(m);
  }

  Future<void> _setColor(String c) async {
    await _api?.setColor(c);
  }

  Future<void> _stop() async {
    await _api?.stop();
  }

  @override
  Widget build(BuildContext context) {
    final status = _status;
    final mode = status?.mode ?? 'manual';
    return Scaffold(
      appBar: AppBar(
        title: const Text('Smart Car'),
        actions: [
          IconButton(
            icon: const Icon(Icons.stop_circle),
            tooltip: 'Emergency stop',
            onPressed: _api == null ? null : _stop,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            _connectionBar(),
            _videoView(),
            _statusBar(),
            const Divider(height: 1),
            Expanded(child: _controlArea(mode)),
          ],
        ),
      ),
    );
  }

  Widget _connectionBar() {
    return Padding(
      padding: const EdgeInsets.all(8),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _brainCtrl,
              decoration: const InputDecoration(
                labelText: 'Brain URL',
                isDense: true,
                border: OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: _streamCtrl,
              decoration: const InputDecoration(
                labelText: 'Camera stream URL',
                isDense: true,
                border: OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(width: 8),
          FilledButton(onPressed: _connect, child: const Text('Connect')),
        ],
      ),
    );
  }

  Widget _videoView() {
    final url = _streamCtrl.text.trim();
    return Container(
      height: 220,
      color: Colors.black,
      width: double.infinity,
      child: url.isEmpty
          ? const Center(child: Text('no camera URL'))
          : Mjpeg(
              stream: url,
              isLive: true,
              error: (ctx, err, stack) =>
                  Center(child: Text('stream error: $err', style: const TextStyle(color: Colors.white))),
            ),
    );
  }

  Widget _statusBar() {
    final s = _status;
    final rssi = s?.rssi != null ? '  rssi=${s!.rssi}dBm' : '';
    final search = s != null && s.searchState != 'idle'
        ? '  [${s.searchState.toUpperCase()}]'
        : '';
    final obs = s?.obstacleDist != null
        ? '  obs=${s!.obstacleDist!.round()}cm'
        : s?.obstacleCam == true
            ? '  obs=CAM'
            : '';
    final shadow = s != null && s.mode == 'shadow' && s.shadowState != 'idle'
        ? '  \u25c9${s.shadowState.toUpperCase()}'
        : '';
    final text = s == null
        ? 'not connected'
        : 'mode=${s.mode}  fps=${s.fps}$rssi$obs$search$shadow  '
            'target=${s.target == null ? "\u2014" : "(${s.target!.x},${s.target!.y}) a=${s.target!.area}"}';
    final bg = s?.obstacleDist != null && s!.obstacleDist! <= 15
        ? Colors.red.shade900
        : s?.shadowState == 'hidden'
            ? Colors.indigo.shade900
            : s?.shadowState == 'conceal'
                ? Colors.blue.shade900
                : s?.searchState == 'searching'
                    ? Colors.orange.shade900
                    : s?.target == null
                        ? Colors.black26
                        : Colors.green.shade900;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      color: bg,
      child: Text(text, style: const TextStyle(fontFamily: 'monospace')),
    );
  }

  Widget _controlArea(String mode) {
    return Column(
      children: [
        const SizedBox(height: 8),
        SegmentedButton<String>(
          segments: _modes
              .map((m) => ButtonSegment(value: m, label: Text(m)))
              .toList(),
          selected: {mode},
          onSelectionChanged: _api == null
              ? null
              : (s) => _setMode(s.first),
        ),
        const SizedBox(height: 8),
        if (mode == 'color') _colorRow(),
        Expanded(child: _modeBody(mode)),
      ],
    );
  }

  Widget _colorRow() {
    final selected = _status?.color;
    return Wrap(
      spacing: 8,
      children: _colorPresets
          .map((c) => ChoiceChip(
                label: Text(c),
                selected: selected == c,
                onSelected: _api == null ? null : (_) => _setColor(c),
              ))
          .toList(),
    );
  }

  Widget _modeBody(String mode) {
    if (mode == 'manual') {
      return Center(
        child: Joystick(
          mode: JoystickMode.all,
          listener: (d) {
            _joyX = d.x;
            _joyY = d.y;
          },
        ),
      );
    }
    if (mode == 'shadow') {
      final intel = _status?.intel;
      final shadowSt = _status?.shadowState ?? 'idle';
      return Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Icon(Icons.visibility, size: 18),
              const SizedBox(width: 8),
              Text('SHADOW: ${shadowSt.toUpperCase()}',
                  style: Theme.of(context).textTheme.titleMedium),
            ]),
            const SizedBox(height: 8),
            if (intel != null) ...[
              Text('Target: ${intel['is_moving'] == true ? 'MOVING' : 'STOPPED'}',
                  style: TextStyle(
                      color: intel['is_moving'] == true ? Colors.green : Colors.red,
                      fontFamily: 'monospace')),
              Text('Behavior: ${intel['behavior'] ?? '?'}',
                  style: const TextStyle(fontFamily: 'monospace')),
              Text('Moving: ${intel['moving_pct'] ?? 0}%  Stops: ${intel['total_stops'] ?? 0}',
                  style: const TextStyle(fontFamily: 'monospace')),
              const Divider(),
              Text(intel['summary'] ?? 'Collecting data...',
                  style: const TextStyle(fontFamily: 'monospace', fontSize: 11)),
            ] else
              const Text('Awaiting target...', style: TextStyle(fontFamily: 'monospace')),
          ],
        ),
      );
    }
    return Center(
      child: Text(
        mode == 'person'
            ? 'Following people (YOLOv8n)'
            : 'Following color: ${_status?.color ?? "?"}',
        style: Theme.of(context).textTheme.titleMedium,
      ),
    );
  }
}
