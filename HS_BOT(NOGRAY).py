import pyautogui
import time
#import pygetwindow
import cv2
import numpy as np
import pyautogui
import tkinter
import psutil

_Stage = 0
def _loadTemplate(template_path):
    """Load an image template and return the image and its dimensions."""
    template = cv2.imread(template_path)
    if template is None:
        print("Error: image not found!")
        return None, 0, 0
    
    height, width = template.shape[:2]
    
    print(f"Height: {height}, Width: {width}")
    return template, height, width

def _getScreenshot():
    """Capture the screen and return it as a NumPy array."""
    screen_now = pyautogui.screenshot()
    screen_now_np = np.array(screen_now)
    
    return screen_now_np

def _findTemplateOnScreen(screen, template, threshold=0.7):
    """Find the template on the screen."""
    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    
    # Get coordinates whose match score exceeds the threshold.
    y_coords, x_coords = np.where(result >= threshold)
    
    if len(x_coords) > 0 and len(y_coords) > 0:
        print("Template match found!")
        return x_coords, y_coords  # Return the match coordinates.
    else:
        print("Template match not found.")
        return None, None


def _moveToTemplate(x_coords, y_coords):
    """Move the mouse pointer to the first coordinate, if available."""
    if x_coords is not None and y_coords is not None and len(x_coords) > 0 and len(y_coords) > 0:
        pyautogui.moveTo(x_coords[0], y_coords[0])  # Move to the first match.
        print(f"Pointer moved to: {x_coords[0]}, {y_coords[0]}")
    else:
        print("No coordinates found; the pointer cannot be moved.")

def _chouseStage():
    """Run the original template-selection experiment."""
    template_path = 'templates/example.png'  # Set a relative image path.
    template, template_height, template_width = _loadTemplate(template_path)
    
    if template is None:
        return  # The error has already been handled by _loadTemplate.

    screen = _getScreenshot()
    x_coords, y_coords = _findTemplateOnScreen(screen, template)
    
    if x_coords is not None and y_coords is not None:
        
        print(f"Match coordinates: {x_coords[0]}, {y_coords[0]}")
        _moveToTemplate(x_coords, y_coords)
    else:
        print("Application not found.")

_hsPros = "Hearthstone.exe"


        



def _isHSrun(_hsPros):
  for process in psutil.process_iter(['pid','name']):
     if process.info['name'] == _hsPros: 
         return True
  return False

_mainWindow = tkinter.Tk()
_mainWindow.title("RealPlayer Hearthstone")
_mainWindow.geometry("300x400")
window_is_open = True

_lableTest = tkinter.Label(_mainWindow,text=_isHSrun)

def _onButtonMenu():

    _chouseStage()

def _onButtonstart():
  
  _lableTest.pack(pady=30)

  is_running = _isHSrun(_hsPros)  
  if is_running == 1:
    _lableTest.config(text="Hearthstone is running", fg="green")
    
    _buttonHsMenu.pack(pady=20)
   
  else:
    _lableTest.config(text="Hearthstone is not running", fg="red")
  print(is_running)

  
     

  
        
      
    



def on_closing():
    
    _mainWindow.destroy()
    

def _startBot():
   
      return 0
  


_buttonStart = tkinter.Button(_mainWindow, text="Start",command=_onButtonstart)
_buttonStart.pack(pady=20)
_buttonHsMenu = tkinter.Button(_mainWindow, text="Play!",command=_onButtonMenu)

_mainWindow.protocol("WM_DELETE_WINDOW", on_closing)
_mainWindow.mainloop()
