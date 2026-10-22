# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'ui_bubble.ui'
##
## Created by: Qt User Interface Compiler version 6.8.3
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QLabel, QSizePolicy, QWidget)

class Ui_Form(object):
    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName(u"Form")
        Form.resize(320, 180)
        self.messageLabel = QLabel(Form)
        self.messageLabel.setObjectName(u"messageLabel")
        self.messageLabel.setGeometry(QRect(20, 35, 280, 120))
        font = QFont()
        font.setFamilies([u"\u65b9\u6b63\u9ed1\u4f53\u7b80\u4f53"])
        font.setPointSize(12)
        font.setBold(False)
        self.messageLabel.setFont(font)
        self.messageLabel.setAlignment(Qt.AlignmentFlag.AlignLeading|Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop)
        self.messageLabel.setWordWrap(True)

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)
    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", u"Form", None))
        self.messageLabel.setText(QCoreApplication.translate("Form", u"\u6211\u662f\u6d4b\u8bd5\u6587\u5b571231\u6309\u5b9e\u9645\u53d1\u4f73\u5409\u8985iifiajiwdj\u54e6\u54e6\u82b1\u82b1\u77ed\u6211\u7535\u8bdd\u54e6\u54c8\u6211\u5f97\u597d\u597d\u6211\u7535\u8bdd", None))
    # retranslateUi

