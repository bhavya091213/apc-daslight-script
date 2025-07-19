import mido

HARDWARE_PORT = "APC40 mkII"
VIRTUAL_OUT_PORT = "IAC Driver Bus 1"

# ---- Spec constants ----
TRACK_SELECT_NOTE = 0x33  # decimal 51 (bank select)  (spec) 
DEVICE_VALUE_CCS = list(range(0x10, 0x18))  # 0x10..0x17 device knob values
DEVICE_RING_CCS  = list(range(0x18, 0x20))  # 0x18..0x1F ring type (value 2 = Volume Style)
TRACK_VALUE_CCS  = list(range(0x30, 0x38))  # 0x30..0x37 track knob values
TRACK_RING_CCS   = list(range(0x38, 0x40))  # 0x38..0x3F track ring type

RING_STYLE_VOLUME = 2

# Number of software banks (Track Select 0..7 -> 8 banks)
NUM_BANKS = 8

# Bank state: for each bank store value (0-127) for each of 16 knobs
bank_states = [
    {
        'device': {cc: 0 for cc in DEVICE_VALUE_CCS},
        'track':  {cc: 0 for cc in TRACK_VALUE_CCS},
    }
    for _ in range(NUM_BANKS)
]

active_bank = 0


def build_intro_sysex(mode=0x41, ver=(1, 0, 0)):
    """
    Proper 'Introduction' / 'Mode select' SysEx:
    F0 47 7F 29 60 00 04 <mode> <verMajor> <verMinor> <bugfix> F7
    """
    ver_major, ver_minor, bugfix = ver
    data = [0x47, 0x7F, 0x29, 0x60, 0x00, 0x04, mode, ver_major, ver_minor, bugfix]
    return mido.Message('sysex', data=data)


def send_ring_types(hw):
    """
    Set ALL 16 rings to Volume Style.
    In Mode 1 the device/control & track knobs are unbanked; we address channel 0.
    """
    # Device knob ring types
    for cc in DEVICE_RING_CCS:
        hw.send(mido.Message('control_change', channel=0, control=cc, value=RING_STYLE_VOLUME))
    # Track knob ring types
    for cc in TRACK_RING_CCS:
        hw.send(mido.Message('control_change', channel=0, control=cc, value=RING_STYLE_VOLUME))


def light_track_select(hw, bank):
    """
    Light the selected Track Select pad (bank 0..7).
    We first clear all 8 (velocity 0) then set selected (velocity 127).
    Using note_on with velocity 0 acts similar to note_off but explicit is clearer.
    """
    for ch in range(NUM_BANKS):
        vel = 127 if ch == bank else 0
        hw.send(mido.Message('note_on', channel=ch, note=TRACK_SELECT_NOTE, velocity=vel))


def recall_bank(bank, hw, virt):
    """
    Push stored values for the given bank to hardware (update rings) and virtual out
    (so downstream gets a snapshot). Hardware channel fixed at 0 in Mode 1.
    Virtual out: we keep your previous separation (device -> bank channel,
    track -> bank+8) so external mapping can distinguish.
    """
    # Device knobs
    for cc, val in bank_states[bank]['device'].items():
        # To hardware (update LED ring + internal value)
        hw.send(mido.Message('control_change', channel=0, control=cc, value=val))
        # Virtual (channel = bank)
        virt.send(mido.Message('control_change', channel=bank, control=cc, value=val))
        print(f"[RECALL] Bank {bank} DEVICE cc {hex(cc)} = {val}")

    # Track knobs (software-banked)
    for cc, val in bank_states[bank]['track'].items():
        hw.send(mido.Message('control_change', channel=0, control=cc, value=val))
        virt.send(mido.Message('control_change', channel=bank + 8, control=cc, value=val))
        print(f"[RECALL] Bank {bank} TRACK  cc {hex(cc)} = {val}")


def handle_cc(msg, hw, virt):
    """
    Process incoming CC from hardware:
    - Identify whether device or track knob
    - Store in current bank
    - Forward to virtual (with banked channel mapping)
    - Echo back to hardware only if you want to 'force' ring update (not needed unless smoothing)
    """
    global active_bank

    cc = msg.control
    val = msg.value

    if cc in DEVICE_VALUE_CCS:
        bank_states[active_bank]['device'][cc] = val
        # Virtual out: channel = active_bank
        virt.send(mido.Message('control_change', channel=active_bank, control=cc, value=val))
        # (Optional) Re-send to hardware not required; ring already updates from original message.
        print(f"[STORE] Bank {active_bank} DEVICE cc {hex(cc)} = {val}")

    elif cc in TRACK_VALUE_CCS:
        bank_states[active_bank]['track'][cc] = val
        # Virtual: track knobs on channel bank+8
        virt.send(mido.Message('control_change', channel=active_bank + 8, control=cc, value=val))
        print(f"[STORE] Bank {active_bank} TRACK  cc {hex(cc)} = {val}")

    else:
        # Pass through anything else
        virt.send(msg)
        print(f"[PASS] {msg}")


def handle_track_select(note_msg, hw, virt):
    """
    Incoming track select note_on chooses new bank (channel = target bank).
    """
    global active_bank
    new_bank = note_msg.channel
    if new_bank == active_bank:
        return
    old = active_bank
    active_bank = new_bank
    print(f"[BANK SWITCH] {old} -> {active_bank}")
    light_track_select(hw, active_bank)
    recall_bank(active_bank, hw, virt)


def main():
    global active_bank

    print("MIDI IN:", mido.get_input_names())
    print("MIDI OUT:", mido.get_output_names())

    hw = mido.open_output(HARDWARE_PORT)
    virt = mido.open_output(VIRTUAL_OUT_PORT)

    # Proper Introduction (Mode 1: Ableton Live Mode)
    intro = build_intro_sysex(mode=0x41, ver=(1, 0, 0))
    hw.send(intro)
    print("[INIT] Sent Intro / Mode Select (Mode 1)")

    # Set all ring types once
    send_ring_types(hw)
    print("[INIT] All ring types => Volume Style")

    # Light bank 0
    light_track_select(hw, active_bank)

    # Initial recall (all zeros)
    recall_bank(active_bank, hw, virt)

    print("Listening...")
    with mido.open_input(HARDWARE_PORT) as inp:
        for msg in inp:
            # Track Select button (note_on)
            if msg.type == 'note_on' and msg.note == TRACK_SELECT_NOTE and msg.velocity > 0:
                handle_track_select(msg, hw, virt)
                continue

            # Ignore note_off for track select (LED we manage)
            if msg.type == 'note_off' and msg.note == TRACK_SELECT_NOTE:
                continue

            # CC (absolute)
            if msg.type == 'control_change':
                handle_cc(msg, hw, virt)
                continue

            # Pass any other message through if desired
            virt.send(msg)
            print(f"[OTHER] {msg}")


if __name__ == "__main__":
    main()
