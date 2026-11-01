"""Connection feedback reflects confirmed worker state, never button clicks."""
def connection_color(button, state):
    if button.property('connectionState') == state:
        return
    button.setProperty('connectionState', state)
    color = {'connected': '#238636', 'partial': '#946b16', 'error': '#b42318',
             'pending': '#2469a0'}.get(state)
    button.setStyleSheet('QPushButton { background-color: '+color+'; color: white; padding: 6px; }' if color else '')
