# Published on /festival/event_status (reliable, transient_local, depth 1)
builtin_interfaces/Time stamp
string mode                       # AUTONOMOUS | MANUAL
bool fireworks_enabled
bool lighting_enabled
bool sound_enabled
string lighting_mode              # on | off | dim | bright | twinkle | festive
string last_event                 # e.g. "golden_burst@fw_n1 ACCEPTED (topic)"
uint32 events_triggered
uint32 events_rejected
float32 seconds_to_next_auto_event   # -1 when autonomous mode is off
