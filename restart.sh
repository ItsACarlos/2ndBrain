#!/bin/bash

systemctl --user daemon-reload
systemctl --user restart brain.service
systemctl --user status brain.service --no-pager

journalctl --user -u brain.service -f
