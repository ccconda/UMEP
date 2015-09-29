from PyQt4 import QtCore, QtGui
import traceback
import numpy as np
import scipy.misc as sc
import math
from wallalgorithms import get_ders


class Worker(QtCore.QObject):

    finished = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(Exception, basestring)
    progress = QtCore.pyqtSignal()

    def __init__(self, walls, scale, dsm, dlg):
        QtCore.QObject.__init__(self)
        self.killed = False

        self.dsm = dsm
        self.scale = scale
        self.walls = walls
        self.dlg = dlg

    def run(self):
        ret = None
        try:
            a = self.dsm
            scale = self.scale
            walls = self.walls
            dlg = self.dlg


            # def filter1Goodwin_as_aspect_v3(walls, scale, a):

            row = a.shape[0]
            col = a.shape[1]

            filtersize = np.floor(scale * 9)
            if scale != 1:
                if np.mod(filtersize, scale) == 0:
                    filtersize = filtersize - 1

            filthalveceil = np.ceil(filtersize / 2)
            filthalvefloor = np.floor(filtersize / 2)

            filtmatrix = np.zeros((filtersize, filtersize))
            buildfilt = np.zeros((filtersize, filtersize))

            filtmatrix[:, filthalveceil - 1] = 1
            buildfilt[filthalveceil - 1, 0:filthalvefloor] = 1
            buildfilt[filthalveceil - 1, filthalveceil: filtersize] = 2

            y = np.zeros((row, col)) #%final direction
            z = np.zeros((row, col))#%temporary direction
            x = np.zeros((row, col)) #%building side
            walls[walls > 0] = 1

            for h in range(0, 180):  #=0:1:180 #%increased resolution to 1 deg 20140911
                if self.killed is True:
                        break
                # print h
                filtmatrix1temp = sc.imrotate(filtmatrix, h, 'bilinear')
                filtmatrix1 = np.round(filtmatrix1temp / 255.)
                filtmatrixbuildtemp = sc.imrotate(buildfilt, h, 'nearest')
                filtmatrixbuild = np.round(filtmatrixbuildtemp / 127.)
                index = 270-h
                if h == 150:
                    filtmatrixbuild[:, 8] = 0
                if h == 30:
                    filtmatrixbuild[:, 8] = 0
                if index == 225:
                    n = filtmatrix.shape[0] - 1  #length(filtmatrix);
                    filtmatrix1[0, 0] = 1
                    filtmatrix1[n, n] = 1
                if index == 135:
                    n = filtmatrix.shape[0] - 1  #length(filtmatrix);
                    filtmatrix1[0, n] = 1
                    filtmatrix1[n, 0] = 1

                for i in range(int(filthalveceil)-1, row - int(filthalveceil) - 1):  #i=filthalveceil:sizey-filthalveceil
                    for j in range(int(filthalveceil)-1, col - int(filthalveceil) - 1):  #(j=filthalveceil:sizex-filthalveceil
                        if walls[i, j] == 1:
                            wallscut = walls[i-filthalvefloor:i+filthalvefloor+1, j-filthalvefloor:j+filthalvefloor+1] * filtmatrix1
                            dsmcut = a[i-filthalvefloor:i+filthalvefloor+1, j-filthalvefloor:j+filthalvefloor+1]
                            if z[i, j] < wallscut.sum():  #sum(sum(wallscut))
                                z[i, j] = wallscut.sum()  #sum(sum(wallscut));
                                if np.sum(dsmcut[filtmatrixbuild == 1]) > np.sum(dsmcut[filtmatrixbuild == 2]):
                                    x[i, j] = 1
                                else:
                                    x[i, j] = 2

                                y[i, j] = index

                self.progress.emit()  # move progressbar forward

            y[(x == 1)] = y[(x == 1)] - 180
            y[(y < 0)] = y[(y < 0)] + 360

            grad, asp = get_ders(a, scale)

            y = y + ((walls == 1) * 1) * ((y == 0) * 1) * (asp / (math.pi / 180.))

            dirwalls = y

            wallresult = {'dirwalls': dirwalls}

            # return dirwalls

            # for i in range(skyvaultaltint.size):
            #     for j in range(aziinterval[i]):
            #
            #         if self.killed is True:
            #             break

            if self.killed is False:
                self.progress.emit()
                ret = wallresult
        except Exception, e:
            self.error.emit(e, traceback.format_exc())
        self.finished.emit(ret)

    def kill(self):
        self.killed = True
