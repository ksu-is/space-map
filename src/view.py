import os
from math import cos, e, radians, sin, sqrt

import numpy as np
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from PySide6 import QtCore
from PySide6.QtGui import QImage, QMouseEvent, QTransform
from PySide6.QtOpenGLWidgets import QOpenGLWidget

'''
In MVC, the view is the part of the application that is responsible for displaying the data to the user, and for receiving user input.
The view is not aware of the model, so it does not directly interact with the data. It sends and receives data through the controller.

For space-map, the View has several components:
- MainWindow: The base gui which is empty except for the toolbar. Its job is to serve as a container.
- GlobeView: Responsible for the 3D rendering of the Earth and Satellites. Its front and center as its the main feature of the application.
- ControlPanel: A side panel containing user inputs and associated information.

'''

from enum import Enum

from PySide6.QtCore import (
    QDateTime,
    QEvent,
    QPoint,
    QRect,
    QSettings,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QFont, QIntValidator
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCalendarWidget,
    QComboBox,
    QDateTimeEdit,
    QDockWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPlainTextDocumentLayout,
    QProxyStyle,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from skyfield.toposlib import GeographicPosition
from skyfield.units import Angle, Distance


class AbstractWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.settings = QSettings()
        self.settingsGroup = "default"

    def saveSettings(self):
        self.settings.beginGroup(self.settingsGroup)

        self.settings.setValue("windowState", self.windowState())  # Qt.WindowState
        if not self.windowState() & Qt.WindowState.WindowMaximized:
            self.settings.setValue("size", self.size())  # QSize
            self.settings.setValue("position", self.pos())  # QPoint

        self.settings.endGroup()

    def restoreSettings(self):
        self.settings.beginGroup(self.settingsGroup)
        self.move(self.settings.value("position", QPoint()))
        self.resize(self.settings.value("size", QSize()))
        self.settings.setValue("position", self.pos())  # QPoint
        self.settings.setValue("windowState", self.windowState())  # Qt.WindowState
        self.settings.endGroup()

        self.show()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            QApplication.quit()
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            self.saveSettings()
        super().changeEvent(event)

    def closeEvent(self, event):
        self.saveSettings()
        super().closeEvent(event)

class MainView(AbstractWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Space Map")
        self.settingsGroup = str(self.windowTitle())
        self.initUI()

    def initUI(self):
        # topBar
        self.topBar = QToolBar()
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.topBar)
        self.topBar.addSeparator()

        # Setup the main widget and layout for the satellite input
        self.current_sat_input = QWidget()
        self.current_sat_input_layout = QHBoxLayout()
        self.current_sat_input_layout.setContentsMargins(0, 0, 0, 0)
        self.current_sat_input.setLayout(self.current_sat_input_layout)

        # Create and configure the satellite tracking label
        self.current_sat_label = QLabel("Tracking Satellite:   ")
        self.current_sat_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.current_sat_label.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Create and configure the satellite tracking input
        class IDSpinBox(QSpinBox): # Custom QSpinBox to display leading zeros
            def __init__(self, parent=None):
                super().__init__(parent)
                self.setRange(0, 99999)
                self.setFixedWidth(75)
                self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
                self.setFrame(False)
                self.setAlignment(Qt.AlignmentFlag.AlignLeft)
                self.setAlignment(Qt.AlignmentFlag.AlignVCenter)
                self.setKeyboardTracking(False)

            def textFromValue(self, value):
                return "%05d" % value

        self.current_sat_id_spinbox = IDSpinBox()
        self.current_sat_id_spinbox.editingFinished.connect(self.current_sat_id_spinbox.clearFocus)

        class MyProxyStyle(QProxyStyle):
            def styleHint(self, hint, option=None, widget=None, returnData=None):
                if hint == QStyle.SH_ComboBox_Popup:
                    return 0
                return super().styleHint(hint, option, widget, returnData)

        class MyComboBox(QComboBox):
            def __init__(self):
                super().__init__()

            def showPopup(self):
                super().showPopup()
                popup = self.view().window()
                width = self.width()
                height = 200
                popup.resize(width, height)
                popup.move(self.mapToGlobal(self.rect().bottomLeft()))  # Reposition the popup window

        self.satellite_combobox = MyComboBox()
        self.satellite_combobox.setInsertPolicy(QComboBox.InsertPolicy.InsertAtTop)
        self.satellite_combobox.setStyle(MyProxyStyle())

        # Add widgets to the layout
        self.current_sat_input_layout.addWidget(self.satellite_combobox)
        self.current_sat_input_layout.addWidget(self.current_sat_id_spinbox)
        self.current_sat_input_layout.addStretch(1)

        # Connect mouse event to spinbox for focus management
        self.mousePressEvent = lambda event: self.current_sat_id_spinbox.clearFocus() if self.current_sat_id_spinbox.hasFocus() else None

        # Add actions to the topBar
        self.topBar.addWidget(self.current_sat_input)
        self.quality_Action = self.topBar.addAction("Switch Quality", self.controller.toggle_quality)
        self.display_2D_map_Action = self.topBar.addAction("2D Map", self.controller.display_2D_map)
        self.currentScene_Action = self.topBar.addAction("Switch Scene", self.controller.toggle_scene)



class Globe3DView(QOpenGLWidget):
    """ Render a 3D globe using OpenGL, with different scenes such as GLOBE_VIEW, TRACKING_VIEW, and EXPLORE_VIEW."""
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.renderDistance = 33000
        self.camera = self.Camera(controller)

        self.quality = self.RenderQuality.LOW
        self.current_scene = self.SceneView.GLOBE_VIEW

        self.runtime = QTimer(self)
        self.runtime.timeout.connect(self.update) # run 'onRuntime' when timer ends

        self.satellite_position = None
        self.frame_count = 0

    def run(self):
        self.runtime.start(16) # 60fps

    # Init OpenGL view
    def initializeGL(self):
        glEnable(GL_DEPTH_TEST) # Enable depth testing
        glEnable(GL_TEXTURE_2D) # Enable texture mapping
        glEnable(GL_LIGHTING) # Enable lighting
        glEnable(GL_LIGHT0) # Enable light source 0
        glEnable(GL_COLOR_MATERIAL)  # Enable color materials
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE) # Set color materials to affect both ambient and diffuse components

        self.loadTextures(self.quality) # Set the textures based on the quality

        # sun light0 settings
        sun_position = np.array([-75, 100, 100]) # above and to the right of the Earth
        glLightfv(GL_LIGHT0, GL_POSITION, [sun_position[0], sun_position[1], sun_position[2], 0])
        glLightfv(GL_LIGHT0, GL_AMBIENT, [0.2, 0.2, 0.2, 1]) # ambient: gray
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [1.0, 1.0, 0.8, 1]) # diffuse: yellow
        glLightfv(GL_LIGHT0, GL_SPECULAR, [1, 1, 1, 1]) # specular: white

        # material settings
        glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT, (0.3, 0.3, 0.3, 1.0)) # ambient: gray
        glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE, (0.6, 0.6, 0.6, 1.0)) # diffuse: gray
        glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, (1.0, 1.0, 1.0, 1.0)) # specular: white
        glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 100.0) # shininess: 100 MAX

    # Every frame, draw the OpenGL scene
    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT) # Clear the color and depth buffers
        glLoadIdentity()


        self.drawSkybox() # always draw the skybox

        # draw the current scene
        if self.current_scene == self.SceneView.GLOBE_VIEW:
            self.drawScene_GLOBE_VIEW()
        if self.current_scene == self.SceneView.TRACKING_VIEW:
            self.drawScene_TRACKING_VIEW()
        elif self.current_scene == self.SceneView.EXPLORE_VIEW:
            self.drawScene_EXPLORE_VIEW()

    def drawScene_GLOBE_VIEW(self):
        self.camera.setCameraMode(self.camera.CameraMode.STATIC)
        self.camera.update(np.array([0, 0, 0])) # Look at the origin
        self.drawEarth()
        self.drawClouds()
        self.drawKarmanLine()

    def drawScene_TRACKING_VIEW(self):
        self.camera.setCameraMode(self.camera.CameraMode.FOLLOW)
        satellite = self.controller.current_satellite # get the current satellite object to track

        if self.satellite_position is None:
            self.satellite_position = satellite.calc_sat_pos_xyz() * self.controller.scale
        else:
            if self.frame_count % 3 == 0:
                self.satellite_position = satellite.calc_sat_pos_xyz() * self.controller.scale

        self.frame_count += 1

        velocity = satellite.calc_sat_velocity()
        orientation = satellite.calculate_satellite_orientation(self.satellite_position, satellite)

        self.camera.update(self.satellite_position, orientation, velocity)
        self.drawEarth()
        self.drawSatellite(self.satellite_position, velocity, satellite)
        self.drawClouds()
        self.drawKarmanLine()

    def drawSatellite(self, position, velocity, satellite):
        """ Draw the satellite at the given position. """
        glDisable(GL_BLEND)
        glEnable(GL_LIGHTING)
        glDepthMask(GL_TRUE)
        glColor4f(1.0, 0, 0, 1.0)

        glPushMatrix()
        glTranslatef(*position)

        rotation_axis, rotation_angle = satellite.calculate_satellite_orientation(position, satellite)
        # Apply rotation if necessary
        if np.linalg.norm(rotation_axis) != 0:
            rotation_axis /= np.linalg.norm(rotation_axis)
            glRotatef(rotation_angle, *rotation_axis)

        # Draw satellite (assuming a simple sphere for this example)
        quadric = gluNewQuadric()
        gluQuadricTexture(quadric, GL_FALSE)
        gluSphere(quadric, 0.05, self.earth_triangles, self.earth_triangles)
        glPopMatrix()

        #draw a straight line that points to the center of the earth
        glBegin(GL_LINES)
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glVertex3f(*position)
        glVertex3f(0, 0, 0)
        glEnd()

        # draw velocity vector
        glBegin(GL_LINES)
        glColor4f(0.0, 1.0, 0.0, 1.0)
        glVertex3f(*(position - normalize(velocity) * 0.5))
        glVertex3f(*position)
        glEnd()

        glBegin(GL_LINES)
        glColor(0.0, 1.0, 0.0, .8)
        glVertex3f(*position)
        glVertex3f(*(position + normalize(velocity) * 0.5))
        glEnd()

        # reset color, lighting, and matrix
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glEnable(GL_LIGHTING)
        glDepthMask(GL_TRUE)


    def drawClouds(self):
        # draw clouds
        glDepthMask(GL_FALSE)
        glDisable(GL_LIGHTING)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glEnable(GL_BLEND)

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.earth_clouds)
        glColor4f(1.0, 1.0, 1.0, 0.5)

        quadric = gluNewQuadric()
        gluQuadricTexture(quadric, GL_TRUE)
        gluSphere(quadric, self.controller.Earth.troposphere, self.earth_triangles, self.earth_triangles)

        #glBlendFunc(GL_ONE, GL_ZERO)
        glDisable(GL_BLEND)
        glEnable(GL_LIGHTING)
        glDepthMask(GL_TRUE)
        glColor4f(1.0, 1.0, 1.0, 1)
    def drawKarmanLine(self):
        # draw the karman line, official boundary of space at 100km
        glDepthMask(GL_FALSE)
        glDisable(GL_LIGHTING)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glEnable(GL_BLEND)
        glColor4f(1.0, 1.0, 1.0, 0.5)

        quadric = gluNewQuadric()
        gluQuadricTexture(quadric, GL_FALSE)
        gluSphere(quadric, self.controller.Earth.karman_line, self.earth_triangles, self.earth_triangles)

        #glBlendFunc(GL_ONE, GL_ZERO)
        glDisable(GL_BLEND)
        glEnable(GL_LIGHTING)
        glDepthMask(GL_TRUE)
        glColor4f(1.0, 1.0, 1.0, 1)

    def drawScene_EXPLORE_VIEW(self):
        self.camera.setCameraMode(self.camera.CameraMode.ORBIT)
        self.camera.position = np.array([-40, 0, 0])
        self.camera.update()
        self.drawEarth() # draw the Earth

    def setScene(self, scene):
        # Set the current scene
        self.current_scene = scene
    def getScene(self):
        # Get the current scene
        return self.current_scene
    class SceneView(Enum):
        """ Enum for the different scenes that can be rendered in Globe3DView"""
        GLOBE_VIEW = 0
        TRACKING_VIEW = 1
        EXPLORE_VIEW = 2

        def __str__(self):
            return self.name

    def loadTextures(self, quality):
        if quality == self.RenderQuality.LOW:
            print("Setting quality to low")
            glShadeModel(GL_FLAT)
            self.earth_triangles = 16
            self.lighting_enabled = False
            self.earth_daymap = self.unpackImageToTexture(imagePath=self.controller.Earth.textures_2k["earth_daymap"])
            self.stars_milky_way = self.unpackImageToTexture(imagePath=self.controller.Earth.textures_2k["stars_milky_way"])
            self.earth_clouds = self.unpackImageToTexture(imagePath=self.controller.Earth.textures_2k["earth_clouds"])

        elif quality == self.RenderQuality.HIGH:
            print("Setting quality to high")
            glShadeModel(GL_SMOOTH)
            self.earth_triangles = 256
            self.lighting_enabled = True
            self.earth_daymap = self.unpackImageToTexture(imagePath=self.controller.Earth.textures_8k["earth_daymap"])
            self.stars_milky_way = self.unpackImageToTexture(imagePath=self.controller.Earth.textures_8k["stars_milky_way"])
            self.earth_clouds = self.unpackImageToTexture(imagePath=self.controller.Earth.textures_8k["earth_clouds"])

    def unpackImageToTexture(self, imagePath):
        # Load a texture from an image file
        texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        image = QImage(imagePath)
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, image.width(), image.height(), 0, GL_RGBA, GL_UNSIGNED_BYTE, image.bits())
        return texture

    def drawEarth(self):

        glDepthMask(GL_TRUE) # Re-enable writing to the depth buffer
        glEnable(GL_LIGHTING) # Re-enable lighting
        glDisable(GL_BLEND)

        glEnable(GL_TEXTURE_2D)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.earth_daymap) # Bind active texture to Earth texture

        # draw earth sphere
        glColor4f(1.0, 1.0, 1.0, 1.0)
        quadric = gluNewQuadric()
        gluQuadricTexture(quadric, GL_TRUE)  # Enable texture mapping
        gluSphere(quadric, self.controller.Earth.radius.km, self.earth_triangles, self.earth_triangles)

        # draw north pole
        glColor4f(1.0, 0.0, 0.0, 0.75)
        glRotatef(180, 0, 1, 0)
        quadric = gluNewQuadric()
        gluCylinder(quadric, 0.1, 0.1, self.controller.Earth.radius.km * 1.25, 32, 32)

        # draw south pole
        glColor4f(0.0, 0.0, 1.0, 0.75)
        quadric = gluNewQuadric()
        glRotatef(-180, 0, 1, 0)
        gluCylinder(quadric, 0.1, 0.1, self.controller.Earth.radius.km * 1.25, 32, 32)
    def drawSkybox(self):
        """ Draw a skybox around the scene """
        glDisable(GL_LIGHTING) # Disable lighting for the skybox
        glDepthMask(GL_FALSE) # Disable writing to the depth buffer for the skybox, so it is always drawn behind other objects

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.stars_milky_way) # Bind active texture to stars texture

        # Draw the skybox as a sphere
        glTranslatef(0, 0, 0)
        glScalef(-1, 1, 1)
        quadric = gluNewQuadric()
        gluQuadricTexture(quadric, GL_TRUE)
        gluSphere(quadric, 16000, 32, 32)

        glDepthMask(GL_TRUE) # Re-enable writing to the depth buffer
        glEnable(GL_LIGHTING) # Re-enable lighting

    def resizeGL(self, width, height):
        """ Resize the OpenGL viewport, update the projection matrix, and set the POV Perspective """
        # Update projection matrix on resize
        glViewport(0, 0, width, height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, width / float(height), 1, self.renderDistance)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
    def setQuality(self, quality):
        """ Set the render quality

        Args:
            quality (RenderQuality): The quality of the rendering: LOW or HIGH
        """
        self.quality = quality
        self.loadTextures(quality)
    def getQuality(self):
        """ Return current render quality setting

        Returns:
            RenderQuality: The current render quality setting: LOW or HIGH
        """
        return self.quality
    class RenderQuality(Enum):
        """ Enum for the different render qualities: LOW or HIGH """
        LOW = 0
        HIGH = 1

        def __str__(self):
            return self.name.capitalize()

    class Camera:
        def __init__(self, controller):
            self.controller = controller
            self.mode = self.CameraMode.STATIC # default
            self.target_position = [0, 0, 0]

        def update(self, target_position=None, target_orientation=None, target_velocity=None):
            if target_position is not None:
                self.target_position = target_position

            if self.mode == self.CameraMode.STATIC:
                # Static camera has a fixed position and orientation relative to the target object's position, no user input, and won't rotate along with the object.
                gluLookAt(-40, 0, 0, 0, 0, 0, 0, 0, -1)  # Look at the origin from a distance

            elif self.mode == self.CameraMode.FOLLOW:

                radial_offset = self.controller.Earth.radius.km * 0.25
                up = np.array([0, 0, 1]) # up vector to align with the Earth's poles

                center = normalize(self.target_position)
                eye = self.target_position + center * radial_offset

                view_matrix = look_at(eye, self.target_position, up)
                glLoadMatrixf(view_matrix.T)

            elif self.mode == self.CameraMode.ORBIT:
                # Orbit camera has a fixed distance from the target object, but can be rotated around the object by user input around the object's position. It doesn't rotate alongside the object's rotation, such as earth's spin.
                pass



        def setCameraMode(self, mode):
            self.mode = mode
        def getCameraMode(self):
            return self.mode
        class CameraMode(Enum):
            """ Enum for the different camera modes: STATIC, ORBIT, FOLLOW """
            STATIC = 0
            ORBIT = 1
            FOLLOW = 2



# Utility functions
def normalize(v):
    return v / np.linalg.norm(v)

def compute_normal_of_plane(v1, v2):
    return np.cross(v1, v2)

def look_at(eye, center, up):
    f = normalize(center - eye)  # forward
    s = normalize(np.cross(f, up))  # side
    u = np.cross(s, f)  # recalculate up

    # Create the corresponding rotation matrix
    M = np.identity(4)
    M[0, :3] = s
    M[1, :3] = u
    M[2, :3] = -f

    # Create the translation matrix
    T = np.identity(4)
    T[:3, 3] = -eye

    # Combine rotation and translation into a single matrix
    return np.dot(M, T)
