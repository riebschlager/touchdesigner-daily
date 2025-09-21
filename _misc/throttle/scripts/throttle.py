"""
TouchDesigner Function Throttling and Queuing System

Place this code in a Text DAT and reference it from a Execute DAT or DAT Execute CHOP.
This system provides throttled function execution with immediate first call and configurable delays.
"""

import time
from collections import deque

# Advanced queuing version with proper queue management and safety limits
class AdvancedFunctionThrottler:
    def __init__(self):
        self.throttle_time = 0.1
        self.call_queues = {}
        self.last_execution_time = {}
        self.processing_flags = {}
        
        # Safety limits to prevent queue overflow
        self.max_queue_size = 10  # Maximum items per queue
        self.queue_strategy = "drop_oldest"  # "drop_oldest", "drop_newest", "skip_new"
        self.total_max_queued_items = 100  # Global limit across all queues
        
        # Statistics for monitoring
        self.stats = {
            'dropped_calls': 0,
            'total_calls': 0,
            'active_queues': 0
        }
        
    def set_throttle_time(self, seconds):
        self.throttle_time = seconds
        
    def set_queue_limits(self, max_per_queue=10, strategy="drop_oldest", global_max=100):
        """
        Configure queue safety limits
        
        Args:
            max_per_queue: Maximum items in any single queue
            strategy: "drop_oldest", "drop_newest", "skip_new"
            global_max: Maximum total items across all queues
        """
        self.max_queue_size = max_per_queue
        self.queue_strategy = strategy
        self.total_max_queued_items = global_max
    
    def queue_call(self, function_name, function_ref, *args, **kwargs):
        """
        Queue a function call with overflow protection
        First call executes immediately, subsequent calls are queued with safety limits
        """
        current_time = time.time()
        self.stats['total_calls'] += 1
        # Initialize queue if needed
        if function_name not in self.call_queues:
            self.call_queues[function_name] = deque()
            self.processing_flags[function_name] = False
        
        # Check global queue limit
        total_queued = sum(len(q) for q in self.call_queues.values())
        if total_queued >= self.total_max_queued_items:
            self.stats['dropped_calls'] += 1
            print(f"WARNING: Global queue limit reached ({total_queued} items). Dropping call.")
            return False
        
        # Check individual queue limit and apply strategy
        queue = self.call_queues[function_name]
        print(f"Queue size for '{function_name}': {len(queue)}")
        if len(queue) >= self.max_queue_size:
            if self.queue_strategy == "skip_new":
                self.stats['dropped_calls'] += 1
                print(f"Queue limit reached for '{function_name}': skipping new call (queue size: {len(queue)})")
                return False
            elif self.queue_strategy == "drop_oldest":
                queue.popleft()  # Remove oldest item to make room
                self.stats['dropped_calls'] += 1
                print(f"Queue limit reached for '{function_name}': dropped oldest call (queue size: {len(queue)})")
            elif self.queue_strategy == "drop_newest":
                queue.pop()  # Remove newest item to make room
                self.stats['dropped_calls'] += 1
                print(f"Queue limit reached for '{function_name}': dropped newest call (queue size: {len(queue)})")

        # Add to queue (now with proper space management)
        queue.append((function_ref, args, kwargs, current_time))
        
        # Process queue if not already processing
        if not self.processing_flags[function_name]:
            self._process_queue(function_name)
            
        return True
    
    def _process_queue(self, function_name):
        """Process the queue for a specific function name"""
        if (function_name not in self.call_queues or 
            len(self.call_queues[function_name]) == 0):
            return
            
        self.processing_flags[function_name] = True
        
        # Get next call from queue
        function_ref, args, kwargs, queue_time = self.call_queues[function_name].popleft()
        
        # Check if we need to wait
        current_time = time.time()
        last_exec = self.last_execution_time.get(function_name, 0)
        time_since_last = current_time - last_exec
        
        if time_since_last >= self.throttle_time:
            # Execute immediately
            self._execute_and_continue(function_name, function_ref, args, kwargs)
        else:
            # Schedule for later
            delay = self.throttle_time - time_since_last
            def delayed_exec():
                self._execute_and_continue(function_name, function_ref, args, kwargs)
            
            run(delayed_exec, delayFrames=int(delay * 60))

    def _execute_and_continue(self, function_name, function_ref, args, kwargs):
        """Execute the function and continue processing the queue"""
        try:
            # Execute the function
            function_ref(*args, **kwargs)

            # Update last execution time
            self.last_execution_time[function_name] = time.time()

        except Exception as e:
            print(f"ERROR executing throttled function {function_name}: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # Always reset processing flag and continue queue
            self.processing_flags[function_name] = False

            # Continue processing if more items in queue
            if (function_name in self.call_queues and
                len(self.call_queues[function_name]) > 0):
                self._process_queue(function_name)

    def get_stats(self):
        """Get current queue statistics"""
        total_queued = sum(len(q) for q in self.call_queues.values())
        active_queues = sum(1 for q in self.call_queues.values() if len(q) > 0)
        
        return {
            'total_queued_items': total_queued,
            'active_queues': active_queues,
            'total_calls_made': self.stats['total_calls'],
            'dropped_calls': self.stats['dropped_calls'],
            'drop_rate': self.stats['dropped_calls'] / max(1, self.stats['total_calls']),
            'queue_details': {name: len(queue) for name, queue in self.call_queues.items() if len(queue) > 0}
        }
    
    def clear_queue(self, function_name=None):
        """Clear specific queue or all queues"""
        if function_name:
            if function_name in self.call_queues:
                dropped = len(self.call_queues[function_name])
                self.call_queues[function_name].clear()
                self.processing_flags[function_name] = False
                self.stats['dropped_calls'] += dropped
                return dropped
        else:
            total_dropped = sum(len(q) for q in self.call_queues.values())
            for queue in self.call_queues.values():
                queue.clear()
            for key in self.processing_flags:
                self.processing_flags[key] = False
            self.stats['dropped_calls'] += total_dropped
            return total_dropped
        return 0

# Global advanced throttler with safe defaults
advanced_throttler = AdvancedFunctionThrottler()

# Set conservative defaults for safety
advanced_throttler.set_queue_limits(
    max_per_queue=5,      # Only 5 items per function queue
    strategy="drop_oldest", # Drop old calls when limit hit
    global_max=50         # Maximum 50 total queued items
)

# Monitoring functions
def print_throttler_stats():
    """Utility function to monitor queue health"""
    stats = advanced_throttler.get_stats()
    print("=== Throttler Statistics ===")
    print(f"Total queued items: {stats['total_queued_items']}")
    print(f"Active queues: {stats['active_queues']}")
    print(f"Total calls made: {stats['total_calls_made']}")
    print(f"Dropped calls: {stats['dropped_calls']}")
    print(f"Drop rate: {stats['drop_rate']:.2%}")
    if stats['queue_details']:
        print("Queue details:")
        for name, count in stats['queue_details'].items():
            print(f"  {name}: {count} items")

def emergency_clear_all_queues():
    """Emergency function to clear all queues"""
    dropped = advanced_throttler.clear_queue()
    print(f"Emergency clear: dropped {dropped} queued items")
    return dropped