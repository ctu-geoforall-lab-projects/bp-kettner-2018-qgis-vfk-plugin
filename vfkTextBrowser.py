# -*- coding: utf-8 -*-

"""
/***************************************************************************
 vfkPluginDialog
                                 A QGIS plugin
 Plugin umoznujici praci s daty katastru nemovitosti
                             -------------------
        begin                : 2015-06-11
        git sha              : $Format:%H$
        copyright            : (C) 2015 by Stepan Bambula
        email                : stepan.bambula@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from PyQt4 import QtCore, QtGui
from PyQt4.QtGui import *
from PyQt4.QtCore import QFile, QIODevice, QUrl, QObject, SIGNAL, SLOT, pyqtSlot, pyqtSignal, QTextStream, qWarning, qDebug
from PyQt4.QtSql import QSqlDatabase

from documentBuilder import *
from htmlDocument import *
from latexDocument import *
from richTextDocument import *


class TPair:
    def __init__(self, first=u'', second=u''):
        self.first = first
        self.second = second


class HistoryRecord(QObject):
    def __init__(self):
        QObject.__init__(self)
        self.html = u''
        self.parIds = []
        self.budIds = []
        self.definitionPoint = Coordinates()


class VfkTextBrowser(QTextBrowser):

    class ExportFormat(object):
        Html = 0
        RichText = 1
        Latex = 2

    # signals
    updateHistory = pyqtSignal(QObject)
    showParcely = pyqtSignal(QObject)
    showBudovy = pyqtSignal(QObject)
    currentParIdsChanged = pyqtSignal(bool)
    currentBudIdsChanged = pyqtSignal(bool)
    historyBefore = pyqtSignal(bool)
    historyAfter = pyqtSignal(bool)
    definitionPointAvailable = pyqtSignal(bool)
    switchToPanelImport = pyqtSignal()
    switchToPanelSearch = pyqtSignal(int)

    def __init__(self, parent=None):
        """
        Init function
        """
        super(VfkTextBrowser, self).__init__(parent)

        self.__mCurrentUrl = QUrl()
        self.__mCurrentRecord = HistoryRecord()
        self.__mDocumentBuilder = DocumentBuilder()
        self.__mUrlHistory = []     # list of history records
        self.__mHistoryOrder = -1      # saving current index in history list

        self.connect(self, SIGNAL("anchorClicked(QUrl)"), self.onLinkClicked)
        self.connect(self, SIGNAL("updateHistory"), self.saveHistory)

        self.emit(SIGNAL("currentParIdsChanged"), False)
        self.emit(SIGNAL("currentBudIdsChanged"), False)
        self.emit(SIGNAL("historyBefore"), False)
        self.emit(SIGNAL("historyAfter"), False)

    def currentUrl(self):
        return self.__mCurrentUrl

    def currentParIds(self):
        return self.__mCurrentRecord.parIds

    def currentBudIds(self):
        return self.__mCurrentRecord.budIds

    def currentDefinitionPoint(self):
        return self.__mCurrentRecord.definitionPoint

    def startPage(self):
        self.processAction(QUrl("showText?page=allTEL"))

    def exportDocument(self, task, fileName, format):
        """

        :type task: QUrl
        :type fileName: str
        :type format: self.ExportFormat
        :return: bool
        """
        fileOut = QFile(fileName)

        if not fileOut.open(QIODevice.WriteOnly | QIODevice.Text):
            return False

        taskMap = self.__parseTask(task)
        text = self.__documentContent(taskMap, format)
        streamFileOut = QTextStream(fileOut)
        streamFileOut.setCodec("UTF-8")
        streamFileOut << text
        streamFileOut.flush()

        fileOut.close()

        return True

    def setConnectionName(self, connectionName):
        """

        :type connectionName: str
        """
        self.__mDocumentBuilder = DocumentBuilder(connectionName)

    def __parseTask(self, task):
        """

        :type task: QUrl
        :return: dict
        """
        taskMap = {u'action': task.path()}

        for key, value in task.encodedQueryItems():
            taskMap[unicode(key)] = QUrl.fromPercentEncoding(unicode(value))

        return taskMap


    def goBack(self):
        if len(self.__mUrlHistory) > 1 and len(self.__mUrlHistory) - self.__mHistoryOrder > 0 and self.__mHistoryOrder > 0:
            self.__mCurrentRecord = self.__mUrlHistory[self.__mHistoryOrder - 1]
            self.__mHistoryOrder -= 1 if self.__mHistoryOrder > 0 else self.__mHistoryOrder == 0
            self.setHtml(self.__mCurrentRecord.html)
            self.updateButtonEnabledState()

    def goForth(self):
        if len(self.__mUrlHistory) > 1 and len(self.__mUrlHistory) - self.__mHistoryOrder > 1 and self.__mHistoryOrder >= 0:
            self.__mCurrentRecord = self.__mUrlHistory[self.__mHistoryOrder + 1]
            self.__mHistoryOrder += 1
            self.setHtml(self.__mCurrentRecord.html)
            self.updateButtonEnabledState()

    def saveHistory(self, record):
        if len(self.__mUrlHistory) == 0:
            self.__mUrlHistory.append(record)
            self.__mHistoryOrder = 0
        else:
            self.__mUrlHistory.append(record)
            self.__mHistoryOrder += 1

        self.__mCurrentRecord = self.__mUrlHistory[self.__mHistoryOrder]
        self.updateButtonEnabledState()

    def showHelpPage(self):
        url = "showText?page=help"
        self.processAction(QUrl(url))

    def showInfoAboutSelection(self, parIds, budIds):
        """

        :type parIds: list
        :type budIds: list
        :return:
        """
        url = u''
        if len(parIds) + len(budIds) == 1:
            if len(parIds) == 1:
                url = u"showText?page=par&id={}".format(parIds[0])
            else:
                url = u"showText?page=bud&id={}".format(budIds[0])

            self.processAction(QUrl(url))
            return

        urlPart = u''
        if parIds:
            urlPart = u"&parcely={}".format(u",".join(parIds))
        if budIds:
            urlPart = u"&budovy={}".format(u",".join(budIds))
        if urlPart:
            url = u"showText?page=seznam&type=id{}".format(urlPart)
            self.processAction(QUrl(url))

    def postInit(self):
        self.emit(SIGNAL("currentParIdsChanged"), False)
        self.emit(SIGNAL("currentBudIdsChanged"), False)
        self.emit(SIGNAL("historyBefore"), False)
        self.emit(SIGNAL("historyAfter"), False)
        self.emit(SIGNAL("definitionPointAvailable"), False)

    def documentFactory(self, format):
        """

        :type format: VfkTextBrowser.ExportFormat
        :rtype: VfkDocument
        """
        doc = VfkDocument

        if format == VfkTextBrowser.ExportFormat.Latex:
            doc = LatexDocument()
            return doc
        elif format == VfkTextBrowser.ExportFormat.Html:
            doc = HtmlDocument()
            return doc
        elif format == VfkTextBrowser.ExportFormat.RichText:
            doc = RichTextDocument()
            return doc
        else:
            qDebug("Nejsou podporovany jine formaty pro export")

    def updateButtonEnabledState(self):
        self.emit(SIGNAL("currentParIdsChanged"), True if self.__mCurrentRecord.parIds else False)
        self.emit(SIGNAL("currentBudIdsChanged"), True if self.__mCurrentRecord.budIds else False)

        self.emit(SIGNAL("historyBefore"), self.__mHistoryOrder > 0)
        self.emit(SIGNAL("historyAfter"), len(self.__mUrlHistory) - self.__mHistoryOrder > 1)

        self.emit(SIGNAL("definitionPointAvailable"), True if (self.__mCurrentRecord.definitionPoint.first
                                                    and self.__mCurrentRecord.definitionPoint.second) else False)

    def onLinkClicked(self, task):
        """

        :type task: QUrl
        """
        self.processAction(task)

    def processAction(self, task):
        """

        :type task: QUrl
        """
        self.__mCurrentUrl = task

        taskMap = self.__parseTask(task)

        if taskMap[u"action"] == u"showText":
            QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            t = QtCore.QTime()
            t.start()
            html = self.__documentContent(taskMap, self.ExportFormat.RichText)
            qDebug("Total time elapsed: {} ms".format(t.elapsed()))
            QApplication.restoreOverrideCursor()
            self.setHtml(html)

            record = HistoryRecord()
            record.html = html
            record.parIds = self.__mDocumentBuilder.currentParIds()
            record.budIds = self.__mDocumentBuilder.currentBudIds()
            record.definitionPoint = self.__mDocumentBuilder.currentDefinitionPoint()

            self.emit(SIGNAL("updateHistory"), record)

        elif taskMap[u"action"] == u"selectInMap":
            self.emit(SIGNAL("showParcely"), taskMap[u'ids'].split(u','))
        elif taskMap[u"action"] == u"switchPanel":
            if taskMap[u"panel"] == u"import":
                self.emit(SIGNAL("switchToPanelImport"))
            elif taskMap[u"panel"] == u"search":
                self.emit(SIGNAL("switchToPanelSearch"), int(taskMap[u'type']))
            self.setHtml(self.__mCurrentRecord.html)
        else:
            qDebug("..Jina akce")

    def __documentContent(self, taskMap, format):
        """

        :type taskMap: dict
        :type format: VfkTextBrowser.ExportFormat
        :return:
        """
        doc = self.documentFactory(format)
        if not doc:
            return ''

        self.__mDocumentBuilder.buildHtml(doc, taskMap)
        text = doc.toString()
        return u'{}'.format(text)
