﻿import os, sys
import unittest
import vtk, qt, ctk, slicer
from slicer.ScriptedLoadableModule import *
import logging
import dicom
from dicom.filereader import InvalidDicomError
from DICOMScalarVolumePlugin import DICOMScalarVolumePluginClass
import PythonQt

#
# PhantomSegmenter
#

class PhantomSegmenter(ScriptedLoadableModule):
  """Uses ScriptedLoadableModule base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def __init__(self, parent):
    ScriptedLoadableModule.__init__(self, parent)
    self.parent.title = "Phantom Segmenter"
    self.parent.categories = ["Segmentation"]
    self.parent.dependencies = []
    self.parent.contributors = ["Colin McCurdy, Mohamed Moselhy (Western University)"]
    self.parent.helpText = """
This module automatically segments a phantom using 3DSlicer's Grow From Seeds algorithm
"""
    self.parent.helpText += self.getDefaultModuleDocumentationLink()
    self.parent.acknowledgementText = """
This file was originally developed by Colin McCurdy and Mohamed Moselhy
"""

#
# PhantomSegmenterWidget
#

class PhantomSegmenterWidget(ScriptedLoadableModuleWidget):
  """Uses ScriptedLoadableModuleWidget base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setup(self):
    ScriptedLoadableModuleWidget.setup(self)

    # Instantiate and connect widgets ...

    self.parametersCollapsibleButton = ctk.ctkCollapsibleButton()
    self.parametersCollapsibleButton.text = "Parameters"
    self.layout.addWidget(self.parametersCollapsibleButton)

    self.parametersFormLayout = qt.QFormLayout(self.parametersCollapsibleButton)

    #
    # input volume selector
    #
    self.inputVolumeSelector = slicer.qMRMLNodeComboBox()
    self.inputVolumeSelector.nodeTypes = ["vtkMRMLScalarVolumeNode"]
    self.inputVolumeSelector.selectNodeUponCreation = True
    self.inputVolumeSelector.addEnabled = True
    self.inputVolumeSelector.removeEnabled = True
    self.inputVolumeSelector.renameEnabled = True
    self.inputVolumeSelector.noneEnabled = False
    self.inputVolumeSelector.showHidden = False
    self.inputVolumeSelector.showChildNodeTypes = False
    self.inputVolumeSelector.setMRMLScene(slicer.mrmlScene)
    self.inputVolumeSelector.setToolTip("Pick the input to the algorithm.")

    self.inputModeLabel = qt.QLabel("Pick input mode:")
    self.loadFromVolume = qt.QRadioButton("Load from Volume")
    self.loadFromVolume.checked = True
    self.loadFromDicom = qt.QRadioButton("Load from DICOM")


    self.inputDicomSelector = ctk.ctkDirectoryButton()
    self.inputDicomSelector.caption = 'Input DICOMs'
    self.inputDicomSelector.directory = os.path.join(os.path.expanduser("~"), "Documents")
    self.loadDicomsButton = qt.QPushButton("Import and Load")
    self.dicomVolumeNode = None

    self.importDicomLayout = qt.QHBoxLayout()
    self.importDicomLayout.addWidget(self.inputDicomSelector, 9)
    self.importDicomLayout.addWidget(self.loadDicomsButton, 1)

    self.parametersFormLayout.addRow(self.inputModeLabel)
    self.parametersFormLayout.addRow(self.loadFromVolume, self.inputVolumeSelector)
    self.parametersFormLayout.addRow(self.loadFromDicom, self.importDicomLayout)

    self.seedCoords = {}

    # Seed selector
    self.seedFiducialsNodeSelector = slicer.qSlicerSimpleMarkupsWidget()
    self.seedFiducialsNodeSelector.objectName = 'seedFiducialsNodeSelector'
    self.seedFiducialsNodeSelector.toolTip = "Select a fiducial to use as the origin of the segments."
    self.seedFiducialsNodeSelector.setNodeBaseName("Seed")
    self.seedFiducialsNodeSelector.defaultNodeColor = qt.QColor(0,255,0)
    self.seedFiducialsNodeSelector.tableWidget().hide()
    self.seedFiducialsNodeSelector.markupsSelectorComboBox().noneEnabled = False
    self.seedFiducialsNodeSelector.markupsPlaceWidget().placeMultipleMarkups = slicer.qSlicerMarkupsPlaceWidget.ForcePlaceSingleMarkup    
    self.seedFiducialsNodeSelector.markupsPlaceWidget().buttonsVisible = False
    self.seedFiducialsNodeSelector.markupsPlaceWidget().placeButton().show()
    self.seedFiducialsNodeSelector.setMRMLScene(slicer.mrmlScene)

    self.seedFiducialsBox = qt.QHBoxLayout()
    self.seedLabelWidget = qt.QLabel("Choose seed node:")
    self.seedFiducialsBox.addWidget(self.seedLabelWidget)
    self.seedFiducialsBox.addWidget(self.seedFiducialsNodeSelector)

    #
    # Setup Button
    #
    self.setupButton = qt.QPushButton("Setup")
    self.setupButton.toolTip = "Setup the algorithm."
    self.setupButton.enabled = False
    self.layout.addWidget(self.setupButton)

    #
    # Apply Button
    #
    self.applyButton = qt.QPushButton("Autosegment")
    self.applyButton.toolTip = "Autosegment the phantom."
    self.applyButton.enabled = False
    self.layout.addWidget(self.applyButton)

    # connections
    self.setupButton.connect('clicked(bool)', self.onSetupButton)
    self.applyButton.connect('clicked(bool)', self.onApplyButton)
    self.inputVolumeSelector.connect("currentNodeChanged(vtkMRMLNode*)", self.onSelect)
    self.loadFromVolume.connect("clicked(bool)", self.onSelect)
    self.loadFromDicom.connect("clicked(bool)", self.onSelect)
    self.loadDicomsButton.connect("clicked(bool)", self.onDicomImportClicked)
    self.loadDicomsButton.connect("clicked(bool)", self.onSelect)
    self.parent.connect('mrmlSceneChanged(vtkMRMLScene*)',
                        self.seedFiducialsNodeSelector, 'setMRMLScene(vtkMRMLScene*)')

    self.tmpNodes = []

    # Add vertical spacer
    self.layout.addStretch(1)

    # Refresh Apply button state
    self.onSelect()

  def onDicomImportClicked(self):
    self.dicomVolumeNode = self.loadDicoms(self.inputDicomSelector.directory)
    self.inputVolumeSelector.setCurrentNode(self.dicomVolumeNode)

  def cleanup(self):
    for tmpNode in self.tmpNodes:
      slicer.mrmlScene.RemoveNode(tmpNode)
    self.parametersFormLayout.removeItem(self.seedFiducialsBox)
    self.applyButton.enabled = False
    self.setupButton.enabled = False

  def onSelect(self):
    if self.loadFromVolume.checked:
      self.masterVolumeNode = self.inputVolumeSelector.currentNode()

    else:
      self.masterVolumeNode = self.dicomVolumeNode

    self.setupButton.enabled = self.masterVolumeNode and slicer.mrmlScene.GetNodeByID(self.masterVolumeNode.GetID())

  def onSetupButton(self):
    prompt = ctk.ctkMessageBox()
    scriptpath = os.path.dirname(__file__)
    iconpath = os.path.join(scriptpath, 'Resources', 'Icons', 'PhantomSegmenter.png')
    iconpath = iconpath.replace('\\', '/')
    icon = qt.QIcon(iconpath)
    prompt.setWindowIcon(icon)
    prompt.setWindowTitle("Add seeds")
    prompt.setIcon(qt.QMessageBox.Information)
    prompt.setText("Add at least one seed to the background, phantom, and feature using the seed node selector on the left, then click \"%s\"" % self.applyButton.text)
    prompt.setStandardButtons(qt.QMessageBox.Ok | qt.QMessageBox.Cancel)
    prompt.setDefaultButton(qt.QMessageBox.Ok)
    answer = prompt.exec_()
    self.parametersFormLayout.addRow(self.seedFiducialsBox)


    if answer == qt.QMessageBox.Cancel:
        logging.info("Operation cancelled by user, terminating...")
        return

    self.bgNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Background")
    self.phantomNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Phantom")
    self.featureNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode", "Feature")

    self.tmpNodes = [self.bgNode, self.phantomNode, self.featureNode]

    self.bgNode.AddObserver(slicer.vtkMRMLMarkupsNode.MarkupAddedEvent, self.onSeedSelect)
    self.phantomNode.AddObserver(slicer.vtkMRMLMarkupsNode.MarkupAddedEvent, self.onSeedSelect)
    self.featureNode.AddObserver(slicer.vtkMRMLMarkupsNode.MarkupAddedEvent, self.onSeedSelect)

    self.bgNode.GetDisplayNode().SetSelectedColor(0,1,0)
    self.phantomNode.GetDisplayNode().SetSelectedColor(1,0,0)
    self.featureNode.GetDisplayNode().SetSelectedColor(0,0,1)

    self.seedFiducialsNodeSelector.setCurrentNode(self.bgNode)

  def onSeedSelect(self, caller, event):
    if self.bgNode and self.phantomNode and self.featureNode:
      self.applyButton.enabled = self.bgNode.GetNumberOfMarkups() and self.phantomNode.GetNumberOfMarkups() and self.featureNode.GetNumberOfMarkups()
    else:
      self.applyButton.enabled = False

  def onApplyButton(self):
    self.addSeedCoords(self.bgNode)
    self.addSeedCoords(self.phantomNode)
    self.addSeedCoords(self.featureNode)

    self.logic = PhantomSegmenterLogic()
    self.logic.run(self.masterVolumeNode, self.seedCoords)

    self.cleanup()

  def addSeedCoords(self, fidNode):
    seed = fidNode.GetName()
    if seed not in self.seedCoords:
        self.seedCoords[seed] = []
    
    for n in range(fidNode.GetNumberOfMarkups()):
        ras = [0,0,0]
        fidNode.GetNthFiducialPosition(n, ras)
        self.seedCoords[seed].append(ras)

  def loadDicoms(self, dcmpath):
    volArray = []

    files = os.listdir(dcmpath)
    files = [os.path.join(dcmpath, file) for file in files]
    volDir = self.inputDicomSelector.directory

    for file in files:
      if os.path.isfile(file):
        try:
          ds = dicom.read_file(file)
          sn = ds.SeriesNumber
          volArray.append(file)
        except InvalidDicomError as ex:
          pass

    if len(volArray) == 0:
      logging.info("No DICOMs were found in directory " + dcmpath)
      logging.info("Doing recursive search...")

      qt.QApplication.setOverrideCursor(qt.Qt.WaitCursor)
      recdcms = self.findDicoms(dcmpath)
      qt.QApplication.restoreOverrideCursor()

      if len(recdcms) == 0:
        return None

      else:
        keys = recdcms.keys()
        diag = qt.QInputDialog()
        scriptpath = os.path.dirname(__file__)
        iconpath = os.path.join(scriptpath, 'Resources', 'Icons', 'PhantomSegmenter.png')
        iconpath = iconpath.replace('\\', '/')
        icon = qt.QIcon(iconpath)
        diag.setWindowIcon(icon)
        ok = PythonQt.BoolResult()
        sn = qt.QInputDialog.getItem(diag, "Pick Volume", "Choose Series Number:", keys, 0, False, ok)
        volArray = recdcms[str(sn)]
        volDir = os.path.dirname(volArray[0])

        if not ok:
          logging.error("No volume selected. Terminating...")
          return None


    self.inputDicomSelector.directory = volDir
    importer = DICOMScalarVolumePluginClass()
    volNode = importer.load(importer.examine([volArray])[0])
    volNode.SetName(str(sn))
      
    return volNode

  def findDicoms(self, dcmpath):
    dcmdict = {}
    for root, dirs, files in os.walk(dcmpath):
      files = [os.path.join(root, filename) for filename in files]
      for file in files:
        try:
          ds = dicom.read_file(file)
          sn = str(ds.SeriesNumber)
          if sn not in dcmdict:
            dcmdict[sn] = []
          dcmdict[sn].append(file)
        except Exception as e:
          pass

    if len(dcmdict) == 0:
      logging.error("No DICOMs were recursively found in directory " + dcmpath)

    return dcmdict


#
# PhantomSegmenterLogic
#


class PhantomSegmenterLogic(ScriptedLoadableModuleLogic):

  def run(self, masterVolumeNode, seedCoords):
    # for each volume we will perform the segmentation
    # much of this code is based off of https://subversion.assembla.com/svn/slicerrt/trunk/SlicerRt/samples/PythonScripts/SegmentGrowCut/SegmentGrowCutSimple.py

    # setup the segmentation node for our DICOM volume - "masterVolumeNode"
    segmentationNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
    segmentationNode.SetName("%s_segmentation" % masterVolumeNode.GetName())
    segmentationNode.CreateDefaultDisplayNodes()
    segmentationNode.SetReferenceImageGeometryParameterFromVolumeNode(masterVolumeNode)

    # create segment seed(s) for phantom volume
    # volSeedPositions = ([50.5,24.9,32.4], [-50.5,24.9,32.4],[-50.5,24.9,-62.4]) # change these based on phantom location in image
    volSeedPositions = seedCoords['Phantom'] # change these based on phantom location in image
    append = vtk.vtkAppendPolyData()
    for volSeedPosition in volSeedPositions:
      # create a seed as a sphere
      volSeed = vtk.vtkSphereSource()
      volSeed.SetCenter(volSeedPosition) 
      volSeed.SetRadius(10) # change this based on size of phantom or preference
      volSeed.Update()
      append.AddInputData(volSeed.GetOutput())

    append.Update()
    
    # add segmentation to the segmentationNode. "Phantom" can be any string, and the following double array is colour.
    volSegID = segmentationNode.AddSegmentFromClosedSurfaceRepresentation(append.GetOutput(), "Phantom", [1.0,0.0,0.0])

    # create segment seed(s) for the background noise
    # bgSeedPositions = ([47,124,8],[-47,-80,8],[44,-90,32], [63,-83,6], [-68,106,-56]) # change these based on where the background/noise is in your image
    bgSeedPositions = seedCoords['Background'] # change these based on where the background/noise is in your image
    appendBg = vtk.vtkAppendPolyData()
    for bgSeedPos in bgSeedPositions:
      bgSeed = vtk.vtkSphereSource()
      bgSeed.SetCenter(bgSeedPos) 
      bgSeed.SetRadius(10)# change this based on background size
      bgSeed.Update()
      appendBg.AddInputData(bgSeed.GetOutput())

    appendBg.Update()
    
    # add background segmentation to the segmentationNode. Change the name or colour inputs based on preference.
    segmentationNode.AddSegmentFromClosedSurfaceRepresentation(appendBg.GetOutput(), "Background", [0.0,1.0,0.0])

    # create segmentation seed(s) for any additional feature that you wish to segment out
    # featSeedPositions = ([32, -35, -11],[-28,-35,11],[-50,-35,11],[-15,42,18],[-15,30,18]) # change this based on the location of feature(s)
    featSeedPositions = seedCoords['Feature'] # change this based on the location of feature(s)
    appendFeat = vtk.vtkAppendPolyData()
    for featSeedPos in featSeedPositions:
      featSeed = vtk.vtkSphereSource()
      featSeed.SetCenter(featSeedPos) 
      featSeed.SetRadius(2) # small sphere for small features. Change depending on size of objects in your phantom
      featSeed.Update()
      appendFeat.AddInputData(featSeed.GetOutput())

    appendFeat.Update()
    
    # add feature segmentation seeds to the segmentationNode. Change the name or colour based on preference.
    segmentationNode.AddSegmentFromClosedSurfaceRepresentation(appendFeat.GetOutput(), "Feature", [0.0,0.0,1.0])

    # startup segmentEditor to grow seeds and any additional effects
    segmentEditorWidget = slicer.qMRMLSegmentEditorWidget()
    # segmentEditorWidget.show() # this is for debugging if you need to!
    segmentEditorWidget.setMRMLScene(slicer.mrmlScene)
    segmentEditorNode = slicer.vtkMRMLSegmentEditorNode()
    slicer.mrmlScene.AddNode(segmentEditorNode)
    segmentEditorWidget.setMRMLSegmentEditorNode(segmentEditorNode)
    segmentEditorWidget.setSegmentationNode(segmentationNode)
    segmentEditorWidget.setMasterVolumeNode(masterVolumeNode)

    # grow from seeds
    segmentEditorWidget.setActiveEffectByName("Grow from seeds")
    effect = segmentEditorWidget.activeEffect()
    effect.self().onPreview()
    
    # for troubleshooting / editing the seed growth, stop before the onApply() function
    effect.self().onApply()

    # grow the background further into the phantom volume segmentation
    # i needed this as my images had a noisy edge to the phantom volume, so it picked up to much noise as phantom volume
    segmentEditorWidget.setActiveEffectByName("Margin")
    mEffect = segmentEditorWidget.activeEffect()
    segmentEditorWidget.setCurrentSegmentID('Background') # change this based on your needs: does a segment not get all of your volume, or too much?
    mEffect.setParameter('MarginSizeMm', 8.0) # change 8.0 based on how well your segmentation performed. Change to negative if you need to shrink instead of grow.
    mEffect.self().onApply()

    # cleanup segment editor node
    slicer.mrmlScene.RemoveNode(segmentEditorNode)

class PhantomSegmenterTest(ScriptedLoadableModuleTest):
  """
  This is the test case for your scripted module.
  Uses ScriptedLoadableModuleTest base class, available at:
  https://github.com/Slicer/Slicer/blob/master/Base/Python/slicer/ScriptedLoadableModule.py
  """

  def setUp(self):
    """ Do whatever is needed to reset the state - typically a scene clear will be enough.
    """
    slicer.mrmlScene.Clear(0)

  def runTest(self):
    """Run as few or as many tests as needed here.
    """
    self.setUp()
    self.test_PhantomSegmenter1()

  def test_PhantomSegmenter1(self):
    """ Ideally you should have several levels of tests.  At the lowest level
    tests should exercise the functionality of the logic with different inputs
    (both valid and invalid).  At higher levels your tests should emulate the
    way the user would interact with your code and confirm that it still works
    the way you intended.
    One of the most important features of the tests is that it should alert other
    developers when their changes will have an impact on the behavior of your
    module.  For example, if a developer removes a feature that you depend on,
    your test should break so they know that the feature is needed.
    """

    self.delayDisplay("Starting the test")
    #
    # first, get some data
    #
    import urllib
    downloads = (
        ('http://slicer.kitware.com/midas3/download?items=5767', 'FA.nrrd', slicer.util.loadVolume),
        )

    for url,name,loader in downloads:
      filePath = slicer.app.temporaryPath + '/' + name
      if not os.path.exists(filePath) or os.stat(filePath).st_size == 0:
        logging.info('Requesting download %s from %s...\n' % (name, url))
        urllib.urlretrieve(url, filePath)
      if loader:
        logging.info('Loading %s...' % (name,))
        loader(filePath)
    self.delayDisplay('Finished with download and loading')

    volumeNode = slicer.util.getNode(pattern="FA")
    logic = PhantomSegmenterLogic()
    self.assertIsNotNone( logic.hasImageData(volumeNode) )
    self.delayDisplay('Test passed!')
