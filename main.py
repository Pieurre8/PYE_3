# -*- coding: utf-8 -*-

"""
Application entry point for the PYE3 wind farm analysis tool.

This module initializes the main application components including data manager,
splash screen, and main window. It handles the application startup sequence and
resource loading.

File: main.py
Author: Pierre VAXELAIRE
Created: 25/10/2024
Version: 1.0
"""

import os
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from core.config import config
from core.logbook import LogBook
from core.services.auth_service import AuthService
from core.services.application_error_handler import handle_critical_errors
from core.services.error_recovery import ErrorRecoveryManager

from ui.splash_screen import SplashScreen
from ui.main_window import MainWindow
from core.wind_farm_data_manager import WindFarmDataManager

@ErrorRecoveryManager.file_operation_retry
def load_data(data_path=None, chunk_size=None):
    """Load data from CSV file."""
    # Get logbook for logging
    global_logbook = LogBook()
    username = global_logbook.get_username_from_path()
    
    try:
        if chunk_size:
            WindFarmDataManager.load_data(data_path, chunk_size=chunk_size)
        else:
            WindFarmDataManager.load_data(data_path)
        return True
    except Exception as e:
        global_logbook.log_event(username, "Data Loading Error", f"Error loading data: {e}", "error")
        # If data file doesn't exist, create a default one
        if "No such file or directory" in str(e):
            global_logbook.log_event(username, "Data Creation", "Creating default data file...", "info")
            WindFarmDataManager.create_default_data()
            return True
        return False

def create_empty_data_fallback():
    """
    Create minimal default data if data loading fails.
    Ensures the application can start even without complete data.
    """
    # Import the decorator and apply it internally
    from core.services.error_recovery import ErrorRecoveryManager
    
    @ErrorRecoveryManager.file_operation_retry
    def _create_empty_data_fallback_impl():
        global_logbook = LogBook()
        username = global_logbook.get_username_from_path()
        global_logbook.log_event(
            username,
            "Data Loading Fallback",
            "Creating empty default data to allow application to start",
            level="warning"
        )
        
        # Create minimal data structures
        WindFarmDataManager.create_default_data()
        
        # Show a warning to the user
        QMessageBox.warning(
            None,
            "Data Loading Error",
            "Failed to load application data. The application will start with minimal functionality.\n\n"
            "Please check the log file for details and contact support if the problem persists."
        )
    
    # Call the decorated implementation
    _create_empty_data_fallback_impl()

@handle_critical_errors
def main():
    """
    Application main entry point with enhanced error recovery.
    
    This function is wrapped with handle_critical_errors to ensure that any
    unhandled exceptions are logged and reported to the user.
    """
    app = QApplication(sys.argv)
    
    # Initialize application logging system early
    global_logbook = LogBook(log_file=str(config.get_path("LOG_FILE")))
    username = global_logbook.get_username_from_path()

    # Initialize application data and set window icon with error recovery
    data_file_path = str(config.get_data_file_path("TURBINE_INFO"))
    try:
        load_data(data_file_path)
    except Exception as e:
        # If data loading fails even with retries, use fallback
        create_empty_data_fallback()
    
    ICON_PATH = config.get_path("ICONS_DIR") / "logo_app.ico"
    app.setWindowIcon(QIcon(str(ICON_PATH)))

    # Define paths for splash screen resources
    GIF_DIRECTORY = config.get_path("GIF_DIR")
    LOGO_PATH = config.get_path("ICONS_DIR") / "splash_icon.svg"

    # Verify existence of required resource directories and files
    # Instead of exiting immediately, try to create folders if missing
    if not GIF_DIRECTORY.is_dir():
        try:
            GIF_DIRECTORY.mkdir(parents=True, exist_ok=True)
            global_logbook.log_event(username, "Resource Creation", f"Created missing GIF directory: {GIF_DIRECTORY}", "info")
        except Exception as e:
            global_logbook.log_event(username, "Resource Error", f"GIF directory not found and could not be created: {GIF_DIRECTORY}", "error")
            global_logbook.log_event(username, "Resource Error", f"Error: {str(e)}", "error")
            QMessageBox.critical(
                None,
                "Resource Error",
                f"GIF directory not found and could not be created: {GIF_DIRECTORY}\n\n"
                f"Error: {str(e)}\n\nThe application will now exit."
            )
            sys.exit(1)

    if not LOGO_PATH.exists():
        global_logbook.log_event(username, "Resource Warning", f"Logo file not found: {LOGO_PATH}", "warning")
        # Instead of exiting, use a fallback logo if available
        fallback_logo = config.get_path("ICONS_DIR") / "fallback_logo.svg"
        if fallback_logo.exists():
            LOGO_PATH = fallback_logo
            global_logbook.log_event(username, "Resource Fallback", f"Using fallback logo: {LOGO_PATH}", "info")
        else:
            QMessageBox.critical(
                None,
                "Resource Error",
                f"Logo file not found: {LOGO_PATH}\n\n"
                "No fallback logo available. The application will now exit."
            )
            sys.exit(1)

    # Initialize the authentication service
    auth_service = AuthService()
    auth_service.logbook = global_logbook

    # Initialize main application window
    window = MainWindow()

    # Configure and display splash screen with loading animations
    splash = SplashScreen(
        gif_dir=str(GIF_DIRECTORY),
        version_text='PYE',
        logo_path=str(LOGO_PATH),
        duration=config.get_setting("splash_duration", 2000),
        background_color=config.get_setting("splash_background_color", "#FFFFFF"),
        border_radius=config.get_setting("splash_border_radius", 10)
    )

    splash.logbook = global_logbook
    splash.show()

    def on_splash_closed():
        """
        Display main window and check for updates when splash screen closes.
        Also monitor initial memory usage.
        """
        # Set the auth service in the main window (if needed)
        if hasattr(window, 'set_auth_service'):
            window.set_auth_service(auth_service)
        
        window.show()
        
        # Use error handling for update checking
        try:
            window.check_for_updates()
        except Exception as e:
            global_logbook.log_event(
                global_logbook.get_username_from_path(),
                "Update Check Error",
                f"Error checking for updates: {str(e)}",
                level="error"
            )
            # Continue execution instead of crashing
        
        # Initialize dashboard with the default selected park
        try:
            selected_park = window._ui['main_layout'].left_menu.combo_box.currentText()
            if selected_park:
                # Update dashboard with selected park
                window._ui['main_layout'].central_content.dashboard_page.update_dashboard(selected_park)
                
                # Update import page with the same selected park
                if hasattr(window._ui['main_layout'].central_content, 'import_raw_data_page'):
                    window._ui['main_layout'].central_content.import_raw_data_page.update_park_name(selected_park)
                
                # Update the title bar to show the selected park
                window._ui['title_bar'].update_selected_park(selected_park)
        except Exception as e:
            global_logbook.log_event(
                global_logbook.get_username_from_path(),
                "Dashboard Initialization Error",
                f"Error initializing dashboard: {str(e)}",
                level="error"
            )
            # Show a warning but allow the application to continue
            QMessageBox.warning(
                window,
                "Dashboard Error",
                "Error initializing the dashboard. Some features may not work correctly.\n\n"
                "Please check the application log for details."
            )
            
        # Monitor memory usage after initialization
        try:
            WindFarmDataManager._monitor_memory_usage()
        except Exception as e:
            # Non-critical, just log the error
            global_logbook.log_event(
                global_logbook.get_username_from_path(),
                "Memory Monitoring Error",
                f"Error monitoring memory usage: {str(e)}",
                level="warning"
            )

    splash.splash_closed.connect(on_splash_closed)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()