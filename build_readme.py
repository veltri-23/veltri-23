#!/usr/bin/env python3
"""Compatibility entry point for the profile repository's existing command."""
import pathlib
import runpy

if __name__ == '__main__':
    runpy.run_path(str(pathlib.Path(__file__).resolve().parent / 'scripts/update_profile.py'), run_name='__main__')
