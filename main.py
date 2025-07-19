import mido

HARD_CODED_MIDI_DEVICE = "APC40 mkII"
IAC_OUTPUT_PORT = "IAC Driver Bus 1"

# Knobs that shift channel via APC40's track select
DYNAMIC_KNOBS = list(range(16, 23))  # knobs 16–22
# Knobs we want to force to follow that detected channel
TOP_ROW_KNOBS = list(range(48, 55))  # knobs 48–54

# Placeholder for current active channel (will update based on knob activity)
active_channel = None

def main():
    global active_channel

    print("Available MIDI input ports:")
    for port in mido.get_input_names():
        print(f" - {port}")

    print("\nAvailable MIDI output ports:")
    for port in mido.get_output_names():
        print(f" - {port}")

    try:
        outport = mido.open_output(IAC_OUTPUT_PORT)
        print(f"\nUsing IAC Driver Output: {IAC_OUTPUT_PORT}")

        with mido.open_input(HARD_CODED_MIDI_DEVICE) as inport:
            print(f"\nListening for MIDI input from: {HARD_CODED_MIDI_DEVICE}")

            for msg in inport:
                # Only process control_change messages
                if msg.type != 'control_change':
                    outport.send(msg)
                    continue

                controller = msg.control
                channel = msg.channel

                # If message is from device control knobs, use this to update the active channel
                if controller in DYNAMIC_KNOBS:
                    if active_channel != channel:
                        active_channel = channel
                        print(f">>> Active channel updated to {active_channel} from knob {controller}")
                    # Forward as-is
                    outport.send(msg)
                    continue

                # If message is from top row knobs, remap to active channel
                if controller in TOP_ROW_KNOBS:
                    if active_channel is not None:
                        modified_msg = msg.copy(channel=(active_channel + 8))
                        outport.send(modified_msg)
                        print(f"Remapped knob {controller} to channel {active_channel}: {modified_msg}")
                    else:
                        print(f"Warning: active channel not yet set. Ignoring knob {controller} until DYNAMIC_KNOB is moved.")
                    continue

                # Forward any other control messages unchanged
                outport.send(msg)

    except IOError as e:
        print(f"\nCould not open MIDI port. Error: {e}")
        print("Check the device names and connections.")

if __name__ == "__main__":
    main()
# Knob 1: 48
# knob 2: 49
# knob 3: 50
# knob 4: 51
# knob 5: 52
# knob 6: 53
# knob 7: 54
# knob 8: 55