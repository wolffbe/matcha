#!/usr/bin/env python3
"""
Parse pytest output and generate audio matching test results chart.

Usage:
    # Run tests and save log
    pytest -v -s tests/api/audio/test_audio_matching.py 2>&1 | tee tests/api/audio/test_audio_matching.log
    
    # Generate chart
    python tests/api/audio/plot_audio_matching.py
"""

import sys
import re
import os
import matplotlib.pyplot as plt

# Import config for thresholds
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_script_dir, '..', '..', '..'))
_config_path = os.path.join(_project_root, 'matching', 'app', 'config.py')

if not os.path.exists(_config_path):
    raise ImportError(f"config.py not found at {_config_path}")

# Parse config.py directly to avoid pydantic dependency
def _parse_config(config_path):
    """Extract threshold values from config.py without importing it."""
    config = {}
    with open(config_path, 'r') as f:
        content = f.read()
    
    for line in content.split('\n'):
        line = line.strip()
        for key in ['audio_threshold', 'audio_offset', 'transcript_threshold', 'transcript_offset']:
            if line.startswith(f'{key}:'):
                if '=' in line:
                    val_str = line.split('=')[1].strip()
                    try:
                        config[key] = float(val_str)
                    except ValueError:
                        pass
    return config

_config = _parse_config(_config_path)
AUDIO_THRESHOLD = (_config.get('audio_threshold', 0.85) - _config.get('audio_offset', 0.03)) * 100
TRANSCRIPT_THRESHOLD = (_config.get('transcript_threshold', 0.85) - _config.get('transcript_offset', 0.01)) * 100
AUDIO_THRESHOLD_RAW = _config.get('audio_threshold', 0.85) * 100
AUDIO_OFFSET_RAW = _config.get('audio_offset', 0.03) * 100
TRANSCRIPT_THRESHOLD_RAW = _config.get('transcript_threshold', 0.85) * 100
TRANSCRIPT_OFFSET_RAW = _config.get('transcript_offset', 0.01) * 100

def parse_pytest_output(lines):
    """Parse pytest output for audio matching results."""
    
    results = {
        'start': [],
        'end': [],
        'middle': [],
        'special': []
    }
    
    # Pattern: "Trim START 13%: audio=86.5%, transcript=76.6%, status=near_match"
    trim_pattern = re.compile(
        r'Trim (START|END|MIDDLE) (\d+)%: audio=([\d.]+)%, transcript=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Exact match: audio=100.0%, transcript=93.4%, status=exact_match"
    exact_pattern = re.compile(
        r'Exact match: audio=([\d.]+)%, transcript=([\d.]+)%, status=(\w+)'
    )
    
    # Pattern: "Different audio: audio=56.8%, transcript=54.3%, status=no_match"
    different_pattern = re.compile(
        r'Different audio: audio=([\d.]+)%, transcript=([\d.]+)%, status=(\w+)'
    )
    
    pending_result = None
    
    for line in lines:
        # Check if this line indicates test passed/failed
        if pending_result is not None:
            if 'PASSED' in line:
                pending_result['pytest_passed'] = True
            elif 'FAILED' in line:
                pending_result['pytest_passed'] = False
            else:
                # Default to checking status if no PASSED/FAILED found
                pending_result['pytest_passed'] = pending_result['status'] in ['near_match', 'exact_match']
            pending_result = None
            continue
        
        # Check trim tests
        match = trim_pattern.search(line)
        if match:
            trim_type = match.group(1).lower()
            trim_pct = int(match.group(2))
            audio = float(match.group(3))
            transcript = float(match.group(4))
            status = match.group(5)
            
            result = {
                'trim': trim_pct,
                'audio': audio,
                'transcript': transcript,
                'status': status,
                'pytest_passed': True  # default
            }
            results[trim_type].append(result)
            pending_result = result
            continue
        
        # Check exact match
        match = exact_pattern.search(line)
        if match:
            result = {
                'name': 'Exact Match',
                'audio': float(match.group(1)),
                'transcript': float(match.group(2)),
                'status': match.group(3),
                'pytest_passed': True
            }
            results['special'].append(result)
            pending_result = result
            continue
        
        # Check different audio
        match = different_pattern.search(line)
        if match:
            result = {
                'name': 'Different Audio',
                'audio': float(match.group(1)),
                'transcript': float(match.group(2)),
                'status': match.group(3),
                'pytest_passed': True
            }
            results['special'].append(result)
            pending_result = result
    
    # Sort by trim percentage
    for key in ['start', 'end', 'middle']:
        results[key].sort(key=lambda x: x['trim'])
    
    return results


def generate_chart(results, output_path='audio_test_results.png'):
    """Generate matplotlib chart from parsed results."""
    
    if not any([results['start'], results['end'], results['middle']]):
        print("No trim test results found to plot.")
        return
    
    audio_threshold = AUDIO_THRESHOLD
    transcript_threshold = TRANSCRIPT_THRESHOLD
    
    # Format offset display (handle negative offsets)
    audio_offset_sign = '-' if AUDIO_OFFSET_RAW >= 0 else '+'
    audio_offset_display = abs(AUDIO_OFFSET_RAW)
    transcript_offset_sign = '-' if TRANSCRIPT_OFFSET_RAW >= 0 else '+'
    transcript_offset_display = abs(TRANSCRIPT_OFFSET_RAW)
    
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
    fig.suptitle(f'Audio Matching Test Results\n'
                 f'Audio Threshold: {audio_threshold:.0f}% ({AUDIO_THRESHOLD_RAW:.0f}% {audio_offset_sign} {audio_offset_display:.0f}% offset) | '
                 f'Transcript Threshold: {transcript_threshold:.0f}% ({TRANSCRIPT_THRESHOLD_RAW:.0f}% {transcript_offset_sign} {transcript_offset_display:.0f}% offset)', 
                 fontsize=14, fontweight='bold')
    
    datasets = [
        ('Trim START', results['start'], (70, 90)),
        ('Trim END', results['end'], (70, 90)),
        ('Trim MIDDLE', results['middle'], (78, 90))
    ]
    
    for ax, (title, data, ylim) in zip(axes, datasets):
        if not data:
            ax.set_title(f'{title} (no data)')
            continue
        
        trim_pcts = [d['trim'] for d in data]
        audio_vals = [d['audio'] for d in data]
        transcript_vals = [d['transcript'] for d in data]
        pytest_results = [d.get('pytest_passed', True) for d in data]
        
        # Calculate pass/fail
        pass_count = sum(1 for p in pytest_results if p)
        
        # Plot lines
        ax.plot(trim_pcts, audio_vals, 'b-', linewidth=2, label='Audio Match %')
        ax.plot(trim_pcts, transcript_vals, 'g-s', linewidth=2, markersize=6, label='Transcript Match %')
        
        # Color markers by pytest result and add tick/cross
        for trim, audio, passed in zip(trim_pcts, audio_vals, pytest_results):
            color = '#22c55e' if passed else '#ef4444'
            ax.plot(trim, audio, 'o', markersize=12, color=color, zorder=5)
            
            # Add tick or cross
            indicator = '✓' if passed else '✗'
            ax.annotate(indicator, (trim, audio), textcoords="offset points", 
                        xytext=(0, 10), ha='center', fontsize=9, fontweight='bold', color=color)
        
        # Threshold lines with details in label
        ax.axhline(y=audio_threshold, color='blue', linestyle='--', alpha=0.7, 
                   label=f'Audio: {audio_threshold:.0f}% ({AUDIO_THRESHOLD_RAW:.0f}% {audio_offset_sign} {audio_offset_display:.0f}%)')
        if ylim[1] >= transcript_threshold:
            ax.axhline(y=transcript_threshold, color='green', linestyle='--', alpha=0.7, 
                       label=f'Transcript: {transcript_threshold:.0f}% ({TRANSCRIPT_THRESHOLD_RAW:.0f}% {transcript_offset_sign} {transcript_offset_display:.0f}%)')
        
        # Shade pass/fail regions based on status (near_match/exact_match vs no_match)
        if trim_pcts:
            min_trim = min(trim_pcts) - 0.5
            max_trim = max(trim_pcts) + 0.5
            
            match_trims = [d['trim'] for d in data if d['status'] in ['near_match', 'exact_match']]
            no_match_trims = [d['trim'] for d in data if d['status'] == 'no_match']
            
            if match_trims and no_match_trims:
                # Boundary between last match and first no_match
                last_match = max(match_trims)
                first_no_match = min(no_match_trims)
                boundary = (last_match + first_no_match) / 2
                ax.axvspan(min_trim, boundary, alpha=0.1, color='green', label='Match region')
                ax.axvspan(boundary, max_trim, alpha=0.1, color='red', label='No match region')
            elif match_trims:
                ax.axvspan(min_trim, max_trim, alpha=0.1, color='green', label='Match region')
            elif no_match_trims:
                ax.axvspan(min_trim, max_trim, alpha=0.1, color='red', label='No match region')
        
        ax.set_ylabel('Match %', fontsize=11)
        ax.set_title(f'{title} ({pass_count}/{len(data)})', fontsize=12, fontweight='bold')
        ax.set_ylim(ylim[0], ylim[1])
        ax.set_xlim(min(trim_pcts) - 0.5, max(trim_pcts) + 0.5)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='lower left', fontsize=8)
    
    # Set x-axis ticks
    all_trims = sorted(set(
        [d['trim'] for d in results['start']] +
        [d['trim'] for d in results['end']] +
        [d['trim'] for d in results['middle']]
    ))
    if all_trims:
        axes[-1].set_xticks(all_trims)
    axes[-1].set_xlabel('Trim Percentage (%)', fontsize=11)
    
    plt.tight_layout()
    plt.subplots_adjust(top=0.9)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"Chart saved to {output_path}")


def main():
    default_log = 'tests/api/audio/test_audio_matching.log'
    default_output = 'tests/api/audio/audio_test_results.png'
    
    # Read from file argument or default
    log_path = sys.argv[1] if len(sys.argv) > 1 else default_log
    output_path = sys.argv[2] if len(sys.argv) > 2 else default_output
    
    # Create output directory if needed
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    try:
        with open(log_path, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: Log file not found: {log_path}")
        print(f"Run: pytest -v -s tests/api/test_audio_matching.py 2>&1 | tee {default_log}")
        sys.exit(1)
    
    results = parse_pytest_output(lines)
    generate_chart(results, output_path)


if __name__ == '__main__':
    main()