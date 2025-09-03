#!/usr/bin/env python3
"""
Test script for widget comm message handling.
This script creates widgets and runs a kernel to test bidirectional communication.
"""

import asyncio
import json
import time
from ipywidgets import IntSlider, VBox, HBox
import ipykernel
from jupyter_client import KernelManager
import threading

def create_test_widgets():
    """Create test widgets for comm message testing."""
    print("Creating test widgets...")
    
    # Create a simple slider
    slider = IntSlider(
        value=0,
        min=0,
        max=100,
        step=1,
        description='Test Slider',
        continuous_update=True
    )
    
    # Create a container
    container = VBox([
        HBox([
            IntSlider(value=0, description='a'),
            IntSlider(value=0, description='b'),
            IntSlider(value=0, description='c')
        ])
    ])
    
    print(f"Created slider with model_id: {slider.model_id}")
    print(f"Created container with model_id: {container.model_id}")
    
    return slider, container

def setup_comm_handling():
    """Set up comm message handling."""
    print("Setting up comm message handling...")
    
    # This would normally be handled by the Jupyter kernel
    # For testing, we'll simulate the comm handling
    
    def handle_comm_msg(comm, msg):
        """Handle incoming comm messages."""
        print(f"Received comm message: {msg}")
        
        if msg.get('method') == 'update':
            state = msg.get('state', {})
            print(f"Updating widget state: {state}")
            
            # Send echo response back
            echo_msg = {
                'method': 'echo_update',
                'state': state
            }
            print(f"Sending echo response: {echo_msg}")
            # In a real kernel, this would be sent back to the frontend
    
    return handle_comm_msg

def run_kernel_test():
    """Run a kernel test with widgets."""
    print("Starting kernel test...")
    
    # Create widgets
    slider, container = create_test_widgets()
    
    # Set up comm handling
    handle_comm = setup_comm_handling()
    
    print("Kernel test ready. Widgets created:")
    print(f"- Slider: {slider.model_id}")
    print(f"- Container: {container.model_id}")
    
    # Keep the script running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Kernel test stopped.")

if __name__ == "__main__":
    run_kernel_test()
