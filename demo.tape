Output assets/demo.gif
Set FontSize 16
Set Width 1200
Set Height 600
Set Theme "Dracula"
Set TypingSpeed 40ms
Set Padding 20

# Version
Type "gw --version"
Enter
Sleep 1s

# Doctor check
Type "gw doctor"
Enter
Sleep 2s

# Calendar today
Type "gw calendar today"
Enter
Sleep 3s

# Gmail count
Type "gw gmail count --query 'is:unread'"
Enter
Sleep 2s

# Gmail list
Type "gw gmail list --max 3"
Enter
Sleep 3s

# Create meeting
Type 'gw meet create --title "Quick sync"'
Enter
Sleep 2s

# Drive list
Type "gw drive list"
Enter
Sleep 2s

# Contacts search
Type 'gw contacts search "Victor"'
Enter
Sleep 2s

# JSON mode
Type "gw calendar next --json"
Enter
Sleep 2s
