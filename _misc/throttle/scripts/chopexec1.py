# me - this DAT
# 
# channel - the Channel object which has changed
# sampleIndex - the index of the changed sample
# val - the numeric value of the changed sample
# prev - the previous sample value
# 
# Make sure the corresponding toggle is enabled in the CHOP Execute DAT.

throttler_module = op('throttle').module
advanced_throttler = throttler_module.advanced_throttler
advanced_throttler.set_throttle_time(0.25)  # 250 ms
advanced_throttler.set_queue_limits(max_per_queue=20, strategy="drop_oldest", global_max=100)

def onOffToOn(channel, sampleIndex, val, prev):
	return

def whileOn(channel, sampleIndex, val, prev):
	return

def onOnToOff(channel, sampleIndex, val, prev):
	return

def whileOff(channel, sampleIndex, val, prev):
	return

def onValueChange(channel, sampleIndex, val, prev):
 
	def my_value_change_handler(ch_name, value, frame_num):
		print(f"THROTTLED FUNCTION EXECUTED: {ch_name} = {value} at frame {frame_num}")

	advanced_throttler.queue_call(
		f"value_change_{channel.name}",
		my_value_change_handler,
		channel.name,
		val,
		absTime.frame
	)
