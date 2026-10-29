"""Source-bound detector rendering; imported only by the viewer or CPU tools."""
import hashlib
import numpy as np
from PyQt5 import QtCore, QtGui

_PALETTE=((72,211,180),(255,174,78),(112,182,255),(239,128,202),
          (184,153,255),(255,112,109),(199,219,96),(73,211,234))


def render_observation(observation, *, boxes=True, masks=True):
    """Paint a view-only overlay; preserve every source RGB/mask pixel in the DTO."""
    pixels=observation.image.pixels.copy()
    colors=[]
    for item in observation.instances:
        color=_PALETTE[hashlib.sha256(item.detection_id.encode()).digest()[0]%len(_PALETTE)]
        colors.append(color)
        if masks:
            pixels[item.mask]=np.rint(pixels[item.mask]*.62+np.array(color)*.38).astype(np.uint8)
            inside=item.mask.copy()
            inside[1:] &= item.mask[:-1];inside[:-1] &= item.mask[1:]
            inside[:,1:] &= item.mask[:,:-1];inside[:,:-1] &= item.mask[:,1:]
            pixels[item.mask & ~inside]=color
    if not boxes:return pixels
    height,width=pixels.shape[:2]
    image=QtGui.QImage(pixels.data,width,height,int(pixels.strides[0]),QtGui.QImage.Format_RGB888).copy()
    # Paint sharp labels/boxes after enlarging tiny sensor input, rather than
    # enlarging a 4px raster label along with the 160px source image.
    scale=max(1.,min(640/width,1080/height))
    if scale>1:image=image.scaled(round(width*scale),round(height*scale),QtCore.Qt.IgnoreAspectRatio,QtCore.Qt.SmoothTransformation)
    image=image.convertToFormat(QtGui.QImage.Format_RGB888)
    painter=QtGui.QPainter(image)
    font=QtGui.QFont('DejaVu Sans');font.setPixelSize(14);painter.setFont(font)
    for item,color in zip(observation.instances,colors):
        ys,xs=np.nonzero(item.mask)
        if not len(xs):continue
        x,y=round(int(xs.min())*scale),round(int(ys.min())*scale)
        x1,y1=round((int(xs.max())+1)*scale)-1,round((int(ys.max())+1)*scale)-1
        painter.setPen(QtGui.QPen(QtGui.QColor(*color),2))
        painter.drawRect(x,y,x1-x,y1-y)
        label=f'{item.label} {item.score:.0%}'
        metrics=painter.fontMetrics();text_width=metrics.horizontalAdvance(label)+8
        top=max(0,y-metrics.height()-4)
        painter.fillRect(QtCore.QRect(x,top,min(text_width,image.width()-x),metrics.height()+4),QtGui.QColor(*color))
        painter.setPen(QtGui.QColor('#0b1220'))
        painter.drawText(x+4,top+metrics.ascent()+2,label)
    painter.end()
    ptr=image.bits();ptr.setsize(image.byteCount())
    return np.frombuffer(ptr,dtype=np.uint8).reshape(image.height(),image.bytesPerLine())[:,:image.width()*3].reshape(image.height(),image.width(),3).copy()
