# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import psutil

from exporter_core import export_chat

APP_TITLE = "微信聊天导出给大模型"
WECHAT_PROCESS_NAMES = {"weixin.exe", "wechat.exe"}

# 与 EXE 文件图标使用同一套图形。
WINDOW_ICON_PNG_BASE64 = """iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAfGUlEQVR42u2bebRld1XnP/v3+51z7333vvfqvVdVqapUqipDkaQyQoQoElMRkKkbmSoEWxAaF5N0Ky0tdqtdVd2oIDYg0lFBERBdWgUooiIghKKNYgJJKklVBpJUah7fqzfd4Zzz++3df5xblSIjOPTqtdpz11n33GGddfb+7eG7v3v/4F+P/78P+afewAzZcsZ9dm/fJP+SD7xh0wY7db2VrYZg/1c1ZoZsvunaYLbN/7+yittsm7/2pmsD9r0vqHwvgsM2J3J9OvP758wycaU1liwPF41kMcudiM/IgAyyjFSVoohlWUaqTBQxMnCYVIBWYgkTAE9umiWrquTIvKZKpaiCuEysqExSJtY1r1GtPOnneg8uPjR37+pD02c+zybb5rdzvX63liHfnYY3+etlewJYeZCl75p4+gvXhiufN+omr3DaOFstjQ1sPscjIoIhJAxwJBI2vFYTQDAxFDAEtfrX+v/14ySMNPwtISieCiEhRHMUKgxMy4Fz811NBxdSdefxqv/lv9/3zS92r7zzWP3QmzzXb0//ZAWcEn7lQZa+Z/L577wkPPf1K8O6s5TISU5wNO3jcLzHZu2IJTNTHBE1E0hWCwo2FAYMh+FIWivAMJLZUGmCYsNTUAPFoTgSnkQgkpHIJErDaWiKa7RxrgOM0u+nY0d73U/cessX38eLHziObfM8ymK/JwVstmvDVtkRf3Zm5CUv77zjxqdnP7zmuB1mf7ynnOGInUyH/bQekMIqnAuWFFFzQ0FOrW59DaBWC2U4FOprc0PFUL8PLcLEEU1Iw/+beCKe0gIRT5LcKgKVZRR4q1zTQj6a5+3lTJ/o7tt74ODbFp7+ib/kps2B67bG71kBm2+6Nmy9bkfcPL36JzeNv/Ojq/3l7Cq/Whxnn+9TyHQ6QI9ZVINE8/aI0K4Wami+ZnJ6NWvPdyTVWjCT2hpOrbyAWa0NxVEh2GmFOSJCJFARqMiJNIhkUrncSnJ6ZbCBhtQZXdqIyXHowf1vXnzWhz7yZEqQJzP7d52YfOWPT77r01N6Qbw9fsH60nOLaU6m2W99rcBakswTzaGIRRPMHDpc1VM+r9RCI/VvanWMUB1ahTgQGbqCwwwqY2g57rTFdPy4dFVtXo2SQJIGpQQqyym0Sal5rSALmjfHwIXsxK491/c3vm/7E8UEeazZ47Zg9tIjsu7tE2+6Y0NjY/tbxRe0x8DNpWNy0o5ZwqHalIizpEFiLZQpnqR+KISgwxVW4ww/h2Ry2uzNhKRCEkcduuvwreYwAqYC4knOeEn7R2Rn8aDtLg4TyYk4KWhYaQ0qMioLJPJaMeq10Rl31Vyve/K2B69k068/DFsE2apnyhserYBL2CQior+5cPWvrW9cMXZH+ZVigW6YToeZ15Nm1pBoGVE90byoBQxnqoEyiRSarLRIlZTKalMHD+Ylc5kF1wA8ilHBMBYI6fRKn8oWHiMADmcZEORHWy8i2c2yczBvpEwKoLRcSte0aJlEC0TJLFku6jI/37WqtWz1WHNt9b6ByKvYts09Wl7/6NV/u+zWHz+aXXFt57kfXNDFdET3+xN6mAWbx2hQmaPSXCrNiJqRUmC2qORYf1EWSsXFcZmwNXK2u0DWyMWyQs6XCVslQTv0CpUTg64cLxalr+BoES2nskClIpXlRA1Sn7kkmpi1mDWRV4+9kOe1r2KlW8aOwcMykwy0TUGgsoYkGiTJLWkmiYxEjpK5qEGda1xSPfuKP+eGtx1i2ybP9t32BBZwrYMduqFx/ms7Wcs9XOytjuvhsGhdzHKSOSp1lMmTUs5CNWCuKFku5/Li1g9xZftq1uXnMu4nCOK/08FMmYuLHCgPcUd3FzfN/Z3cNnsPlnvGGxOmgIoXk0BUATKSesn9CK8Zfw5vHn0xVaxYG5bx7skb2DL9JXYV0yQVImJRPRVeEgElR32OWibasyTtieCnJn8iwe0s2yBPGAPMTGS7uN944Q/cvq5z/mX39e+purrolJxSPUlzYgoMykyO9BZYKut4xZKf4NrR5zGSjTBEMSSLKDoEQAwhj+DE4yWAg5QSt87fxYcP/gk393cxNTKFhJwkgUiwJWFMNnau4CfGr+H8xllUsQKEJGZNMkkCf7J4Fx+fu4udvRMUODuFEcw1MIJZJaLqEu3RzA4cuUd/6fcvZ8eO+LgusNlw18lWu+Z9rHtG5+LNXV3wJ/SYQS5V8lSaUaWMQfQcXOzKD7c28fMrf4VLOpfj8VRaoZqooY8gp7VbXxtGIlFqyUAHVFZxbutsXr7suTRiiy8c34m5JkqDSINSc6ajsq/sytnZOCuzcQpLeJz0JfHxubv57NyD7CkWrZeMZB4jQy0TS84sGmoeJIMUhFLG7ayxP+QvbjrJ5s2OHTvsO1xg9/B5z80m10srNaYHhyuz4Cp1VOapkmdQwYG5RXnj1Lt45bJXQ1LKWOJw4sUbdmrNbSjyI5/19Of6G8WYibMY8LZ1r2AqTPHWBz9mnXZLJAvSFZiJC3Z3b5f99cJhfvvsF8s17dV0teI/H72ZbbP3miZFgZ4pSQTMkUtudTbJ6iBqTsRclJHRnNGx9cCDXHLJacs/HRU3DBWQEdb05QSlJosWpEhBiiQMKi/7FxbldRPv4JXLXk0ZCyKKF48I3yG8fYfAevpaTUkkEkqyGv1HUx4eHLRXr342/3XlK+XA9ByDwjFIOWVqiGeEY0XJOw/dTNcin5r7Nn904gFCylEL9BNsHF0rf3ruv5FrOmuJUXGaYdEhySMpQBQz1wRrrgZg2a7HKuB0HHAylVAi3kp1VAYxZRzqzfP9jRdyw1mvpYwFDi8YYlan1WTpDOHrAiiSSKYoSrREJJLq7y2JWcQsiZmI59v9o7z5vOfyQ/lFTM8uUhWBQfQsJME0557evH1q5gH+9OQ+yogtVkZKGTE6XrPkYl7WWcurxi8QjSDRIRqw5CE5LDlDAi5ky2spN/KECgA3qjiqGqxYMm/zZZJQTfKmZT8DCoJDwII4C5KBOvKsgQ5fDdcCFUZcC+cclUYQyKWJmFjuGlKkSipLlJooNFGo2qKU9h/Oey5pPlEWUJWOWAUZJEdKno8fv59diyetqhwxBaoYIDb54IF77CsLJ/jggfuQlIF6vHpIgkUZFhkOc77zGGkf/YUqeQSiOZJ5qpTJ0d4i14y8iJUjKym1wEltQYVVfOjAr/LCu6/hzw59jtxlZJLxzblbedVdm3j9nT/FfLmIOEeVIu/Z8z+57paXyaf3f4HMNyg0UmqSympfPjJYlMuXrWW9W05/vgelQ6tApQ5Vz86FWTtUJDIZoaoclgKScnbPLrC3t8iebs98alD0IuViFEpBkkCs4wOE/CkVALgIRIUyQZmSxTKzjaPPP+030SI+BG6d/QY3Hv+g3VXeZ7/40K/QHyrnvfvfzy2DnXxi/x/z2cNfYiyMcvPsrfzG4d+1nf199j++/TH6sSQZEs2o1KQypJcUl2U8vXMOzBVQSW2+0aOlpyqD3Hjus2XnFf9WLh1ZKVYKVijvXvsMOVAW+ApiaTx3arW8fOU6iCJEj0QnkjyYD0+pAAMXMUp1VMnJfDFg3FbIBSPrjZSQ4Us1sap5Dq5YJUdnVZ639AV48USUixpXcmwusqpzGZdPbGAuLXJO6xyWxwuxbls2LvshZmOfw4M5jg4WODpY5Oigx0wxYDZVrB6ZwA8MKQVKEUonGgVvuV04Msl4o82qfIzUK3n3+c+URmiw+YG7LFXGD06t4s8u/X5+56IrOW9sglSBU8GSQHwsi/cYjcQhLq/UiZqnFweslOWMhzFKG5zO7mUqWddZy+cu/wx7+nv5wclnMdABCeUd576Fq5c8i5Wts1jTWsnxYpbxbIIPX/rL8vDiIa5ccjEajeV+DC8eA/opMVuVzBcFC/0BaXqBsNQQj6kJXjxVUfBfHtrFS1as40t7H+KdFz1TNOT87K5bDBy/uP4KWd5o8f4j+5GQcWxxgDNBldoNHqcgPkMB1wI7UBONOJIN6adKpCFtEFDTIawBE6Mf+6wbOZvzR9cyVy2QTDHMoiV59tRV9FPBTLnIbNmlWxWsaa7gOROX4jCCcyA6JE1OZRIjIoxe8izmuwP+ZOYwLPFkrRwTAxVODAp2Ls5zztgkk51x/uttf2dI4Bc3XCnJhP94xy1GaAwBkOB9XleUdQz4rixAEqCCqZklC9KrKjAdpjkeyfNmdK1PTAkRZ9GSJFQSZgvlnCRLdrS/IC0aXDV+PuNZk0ojicTAKtR0iA1qykyHSOKCFZP8wctu4PV79/Lmb3xd9sUeeWfMSFAlmDHwPuMbvS5SRX7qsqtkxuDGu263LGsCAVURk2BmAuINdWBOnjAGfG34XqmTGkl54pCKOjQ4zkLsIiI1kLE6v0fSacQfLZEwq0zryK6JQ905JtwoV09ewHjWotSaIlUMBKvZniENJphiRDNmywF7+jP8wNpVfOkFP8r51qBa6AlFJKox72CxShw3Y2xkXKTd4cbdd1vwjZpwoV5xUanpqCSgAkl5yiCYwCqEqmZfJXMt9g2O8UB3L8FnRKvFTqQa3FgimlJqlFpwpTK1I/15xn1HrliyjmRKpYlokcoqVMzUjGiJwiJxaAXRjIEmKjOceNvXXbSxsQYfu+Y6GnMDxAUmn3Y+ew4ctkZnlGlTosLdsUCG3IElZUgk1p4VAUXEPJi3p1aAQqE1EFIRCyGnLyV/deh/48koLaJDJrdeMSWaUplRWU2CTA+6Yuq4YnwNcWjqicRI1mY0G0MxSosSfGAyX0LwGZWqKMJY3qGdt600AxHZ113kwlVLecMFT8NWL5eHv/0wPVNa5662Pfc9ZOOTEyx6j1VKXIxcenZblnU8qaeISc24JKiBqshTAyGCJQIJR8QTgc5Ih08d/AsOLB6m6RtUlobwtl65CiVSC19oYnrQ5fyR5WTOkVBLksyJY/uBv+Sjez5NTCq5y3lo4RC/vvsPeHD+MMHlJDV+//6v8rkHbhEIUqiRcBzo9XjZFRvId+6le3wWt36NPHTzTkKnw9j6dey+/2HzKlx0fkOecaly1RULMjFeiJaGqEByw0LFPbULlNHV1JLVNHQFtJstDuhx/tvOj9D2bawOyJZOKddq840Gi1WJmGdFc4yBllRaSdM35KvHb+G192/hTXdsZtv+HTR9k7fe9Rv8wt038pabf4uRbIQ/eujvedc3P8nbbvo4dxzbj/icQpX5pLbEZ6zNMhjrUH79Hmg2xV12njzwrfvoHpsH8Rw6muzAzBEOHi7ozucIYmah7riYqyHxmQHv8RRQ4SziUQIqHnOe5IWlk5N84uAX+JXbPsmSxihRVdSMSlWiQbT6/vNVwYjLaXg/DIxKpZFWaGH9cXJZzbLmFCWJcVkG/UnWja6jIDGajZEVS1jROZtOs02piiIMkoo2MpaPjhJ27sW3msj5K+l9435LRxfNE6CC+RnhH24dYfeuMcoqBwtQ+z6mDkuPzQKPpMGvnXIBk4RQmhBVxFzAMofLYWL5Un7p9o/gkuPtz9zEsf5c7WJDBVRqdGOk45vY0C3AmEtdnjFxMV+++gNUGJcsWcexYpH3XfkWXrfmRVw4uY77505w2bLzeO81b2Akb1GK5/65GZIJpcGJWLH/wf3EykOnTbh9v0kvQvBYYYgI3sHi3Ii5EPAh1HyAIkgwIWDingQHbDwFhb3WbahTbSkPzkEmNEYymOrz5UO38Z/0hiG1LUSzGjgp9GOilHQ6U9S9QLH5NJANE+uIYHNVXxRn4jO58qyL2Dc/zahkrMharD77YqqkDFKEIHUgN/AivPu653Ak5Hxk914e6A4kG21bqhRE6mcUjxOPmQf1gjjD3LDjIog4tacEQookajic8CTnSC4YQURyD63AxrO/D3BEVRyedmOEvihBYbwq6JYV0RQVzMxEjVoJcTBseHiLZlRmdnDuhIyR8ZyptafJ07of4qgx7NBRFZ71zOUs0ueyNR1+/ov3snOuK3mnbTEBEmoqPUltkk5rQigEEH8qGMpTIsHKCZX5YSe2jgkJX+MIDHzgmUsvZDEVdLIWGgJ/de83+ezNX2L55FmsXrmWLGvwnKVnow5Jw6Zofbo6a6hKZUbCbHYwYMOSKXBQVCUybJiSeIRSjXVab4jn3t4C98sCv/mSy/mpz+3krrm+ZKOjlgqAJLQ7sHwCxsag1USChxDEGh47euARa9/6xBZAZUI1pJsTQrIkSqCviXOaZ3HV+HpClvHAiYN8+Cvb+fzffYVURfAZuCZuULH29cK//4EXsLc3jfN1Ok11nJASSIgVMUq3iuhwpUWEHPcIV32quzxUvneB0oxvTc8ztqLJh156BW//7J3smukTli5FV66EpZMQPJgiKUEZMcSk0cRCZk8dBA0pTSjNUZhITIYOA0iF0gltDldzfOauv+a3/uaPmT45g1+1nKw9Wg9FVBBPdtnypc9w9dMuYfXUMo71uuAcldVDEXXWMCnN6KdT3aO6Fp+14nS24hRUBqIZyzKhJYE9/YLq+DRXLzfe97JLecdXDst9Y8sI7Tba7dUNOCcmIOakdqu8CcpTF0P9GKyvDo8QxFsPJyeTMYiKcxl74jTXfe0XmN17DDoNshXnYlkLCyNAhlVC6Exw5NgMr/nkh/nIv3sz65efw3S/K1HNSkPiUAmFQal1IQQwnQo+MH0nhdXtssqMSiGZ40RV8obJdbx8ydm8dWoND5Zd7GRJ0Qn82g+u4vXfOMacFUgjN5wI3omJA58ZUrfdHg8JnlbAxo2wA3haM+lPNoTmVCGFNWVeW+yrWuzser45m9iXJQZtpbH+HCw1UBogTSAHayCVRwdKFtrce/goL/vtD/DTz32JvOgZz2Ss3RYfE/0qUcaKauhupwxgwue8Y+oy4hlQ/lTBFM1YHhqA8Zrlazg+6DFXlfSqRLvlWU/BLfNKtmRUUhZMnBfEYQkhE3iCiZnHWMCoKymlz3FfWWGYuUwm8wY/0m5z3VSHu+fhq0cGfHs6IjTJpIlqBpaB5iAOxFBpkq1sMDN9ks1/+hk+8fW/5dpLL+fKC9azYnKKJZ1RGllOaY+QkZwem0kg8kgoAIIIh6oBe0slGqzMGkzmOaNmtL0n9AdQRRgbRcyJnTJ3J0MzGmaYJ1LAKXR4vMq5j1EWVBhog2hNiyknmkouBVOTY3bD+JjcN218dW+fE71AluWgOSoBMgciBiJqOX6qgTQneejYDA99cQd8/iu0sybnX3AeP/9jr2Sy3SaqgXNMFwW/duJuiqSYBCtTjTKTOUuGgLekKnMx8jNnnctzOktYTErTOawsIYIkw8pU97xaHhoeyz007HGnIR5jAV3L7RhtuslTpEBfXT0HUA812INlV4KLrJzq8KrxKW4/kPjmYSOpJ3MB9a5O3OqMpoCYmFOC6yDtPupyej7nzoOHedeNf8irX/7DtKZWQopMhQbvWfGM4RiNiQ6zgBpiGIua5FTd0RShqwoipjYcQRlUdTm8pF2f7RwaTqQZxEaAdqZPqYCBBjtJxlyVKJOTzE2SyYTkvgPSlGSOyoy9gwJkwDlrHRNLAt98UDgxL/jM17DTOXAyrDYS1m6jqy5A8gbu+EmEBvsPHOLDv/c5rv+5VdAZZxD73FvMU9npjDREgoYZXNEaJTgw9ZQKCzogEy/Rubr0HRuDVWchnWYd7yozUhJRwbx/pBh6sjS4WLlqwZq0/GqZys8iuHGsnsaoCyQamAXGJFBpxVxcQMam+b7LeuzZ63lor5cqSk09VAauCauWImOTMIgwM19j9EabbNVaBnv2Mjvbg3NgLlZ86uQ+CjMgWDSIalIkRXD80srzmJAGhT+KhYJ2tZYj1SIj3mPtNoyMI0mhWyCZx7wTgsMSJhEs1XDpyS3AmovL5ftwzTEWU5e+9KlsQLRQzwgQLVkmSGaOBsEvF1hFDAucs/447ckFHv62k9n+pDExJq49iiVBF/tIPxrmkdCCRsBSIdKZwGcZAJMh51dXXkas06LU5m/0tcIM+ilyoogczh7gl2c+ynuX/nfWZGs4XvbrZk1/gJUJc3Xnajh/A2bYACjSwhMqYMcpKJxkZpECmKNHtH4p0q2ilVGknv9piLgWwbcleBBRRDK8m7BMp2Rkcp51V81wdC6Tk8e9FdNdrBdF1NWEQRJM8nqiEsVoDKl2tWhax/5ho1VN6Sej49tECvAw2vAcTRPsmjuLl05/nhvXvIKXTJzNie4Amg1IEVLAkgo+mIhgakg/YeVg5kmqweUGcLJ7Yu/8YIZo43J4bl76UYnRJJknWT0Wo7aA0cC7Nu3GOCPNcXyoxOMJbtK8m5SpzgLiuzLfSvRPOnQBrCtSc/POLDijkwkrDMvzYQtdDKuDn2EsxkQrVPx5eSO39Y+xUC2lnybY0xXi4FIG/SW8+lv38MnLOrxtwyp+etdJiBFJCUt1MWU4KKKzIkI37qtT3cbHGZHZst0A0oHjD9y/5kjp2j5UZWHB5Yh4EYI5MnEuQzVDk6OIFfP9k3jpM9pcQmdkApclxIIFt1RG8uUwWeBbBb1elNgHqxxUHgaCDKyOdOKpVCUN87QClSVrMiL/kP6Q35r7c3rFhZzoe+YHGWWxFFctg2KcULR53Y5pbrxqDW9cL/zedJe82ah7FNEJVhkjTc/MXOTAiW8DsIvHUcBWFDPhetk7s6F739Kp7DLpV5WaczJkVizVdXUd2jOcZASXkdRzcqHL3HxkZGRCWu1xTBKminctRsIY2aizsqGUA5VUmmgOFiKMD7DgSfZITWDAIKk0NHIwVZwsL7TB4DzpDiap+lNQTpCKUawaJ8QOLOTs6+Ws8BH6fbAlde8mJUxRfJbR693P+3/7IcykximPFwS/ttGznVi+dfav1cXLDK+izqEOUS81xRRweFQcMqSaiB6nGVrB/OJJ+mFAPjZptNo1259KDC+4zHAeyQW8GSZC7gEjqpGo+QNETlEpHIstZuJZMiXnAktIMsFsMcJgMAJVm3KhwZYfmOTCwS7e+PV78E9bj2qCQSXmHTRyxTns+OwXYEfka18LnNEk+04FbNyosIP+Awc+0Vu99h0jo6t9tVgOmxgiog6xQIpu2LsHrQySYZpAPaKeKlVUs8dxja658SVCawTEzMoSq+qy3dRwgwoGJckM54RBTOIEELGYkMIiF2bn8Qsja1iblmMtz3ies6c/zptu7oO2+F/PHuHisb289KN/T298OcFLjQpzV8PgRubtwCHl3j2fGC7ykwxKylYdjpTuWvjyudtaV6/+MVv0BYlMTWxQOBkMauFNPaKupp8IoH54urorY06sW1haOAqNFjI6BnlLwNfNh0pFUk1n/e7uAzxr5ThTnVY9W2IirWHHadXM2ew8/AAnw3EKFc5qecbCFCM2xmdf3KYoHuD9tzxIchluyejpSVNEIIRozZGG3Xf7Nt57w062bfNcL+lJcQC7thtm0vvQ1e86uWTJC8bPu3iiewDtDoKL0RvqhBQQPGYBkquZV/XDhuKwDQWgTjBvdEuxhWkxlyPNFuQN8IEE+HabT+89xEOf2sGlY4GqLIcloGIpcbA7RxBhNGtQpsSoh5990RV8dqPyF1/axucPLzC7UNEfm8A3G1ieQQhgJCZGM+7ePcc/3PFzmAlbtthTAiG2olxyveenbzkw93vN1yY/9ZdF60KX5vrJ4RwahqSjq4VXX9N4BqhDzNVh3GplSL0UIA6JYHM9sEHNHnkHZvj2OLedmOG2Pcdh0IdYQUr1u1mdFzTVcCFGjs7/GfPdRe7Yc7xmgJYtwy1binU6tXJxylkTzg4ecXbrrjfwsbfvZWG5Z/vWpx6WfmRkfDhd/YEbXhOeceknWXV+0BNaSI8ADSx5EavncUjD1rMOhVcZ8vHDwshqKzFzdRZRgegNjTVSSxGJEZeqGshoLbCdIkjFhmedJONiFwTCWBtrtWCkjXVGjUbLGO0klk42bM8Btb/91ht59/UfZ/NNga3Xfffj8o8MD18b2Loj+l999UYu2fA7XHDR06xswoKrKJxRiRCdQ/3QDYbCqxvOYDqIQyXgsOSHpKeDYUqV0+auiKYhA2r1PIApOBA/LKqGGdidLjiD0cigOaJ02jA+mpM1sLvve8huvvMtfOh1X34y4b+7PUOnLOGFzxpzr9j4DlaseiNLV5/DyEQNOQcOqaitIGK1Mhyoq1Ok5IaJyNAl6slxx3DjkCDORMRMU707QgwxFcOGeqvjpjgBL3WL34lIFqCRQ97AQob0B9jho4dt79Hf5zNf/nX+9j0n2WaPCXr/uF1jZ242eN7zxv2PXPU8nVz6fGmNXUnePNtcPobkDSR4LJPhePwZrakwtIJT7jJ0A3H1JK2KDRFWHb2RmghzwynbU4pwp2c0IimVmM0xKA8yKO60E3Nf4fO3/g3f2Frj/U3bPNuv/6dvmjpjekrYvs1x/aNuevnz2zx9/SjN0SaNLENwkEMBNBrDnrsXojdoPOqmOYQklGd8PnOQrSzBDXv6wQsx1YjJp5K5os+O3Qsc/kjvUdtdPJvqiYB/oZ2TCNu2eTZvDpj9i+4S/S43NAqbbwpsM/+PeR75Z1EIBlu2PP69dg8HkzdsMtjyzyf4li3DfaJi/Ovxr8c/+vg/0VaK+DNP6zwAAAAASUVORK5CYII="""


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def is_wechat_running() -> bool:
    """检测 Windows 微信是否正在运行。"""
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name in WECHAT_PROCESS_NAMES:
                return True
    except (psutil.Error, OSError):
        # 检测本身异常时不阻断导出，让底层给出真实错误。
        return True
    return False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("840x650")
        self.minsize(760, 560)

        try:
            icon_bytes = base64.b64decode(WINDOW_ICON_PNG_BASE64)
            self._window_icon = tk.PhotoImage(data=icon_bytes)
            self.iconphoto(True, self._window_icon)
        except Exception:
            self._window_icon = None

        self.q = queue.Queue()
        self.last_output = None

        pad = ttk.Frame(self, padding=18)
        pad.grid(row=0, column=0, sticky="nsew")

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        pad.grid_columnconfigure(0, weight=1)
        pad.grid_rowconfigure(7, weight=1)

        ttk.Label(
            pad,
            text="微信聊天信息 → 大模型可读 TXT / Markdown / JSON",
            font=("Microsoft YaHei UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")

        tk.Label(
            pad,
            text="⚠ 使用前请先登录 Windows 微信，并保持微信在后台运行。",
            fg="#b45309",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(row=1, column=0, sticky="w", pady=(8, 2))

        ttk.Label(
            pad,
            text="支持私聊与群聊。输入准确备注名、昵称或群名；程序会自动识别。",
        ).grid(row=2, column=0, sticky="w", pady=(2, 16))

        row = ttk.Frame(pad)
        row.grid(row=3, column=0, sticky="ew")
        row.grid_columnconfigure(1, weight=1)

        ttk.Label(row, text="好友 / 群聊：").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.name_var)
        self.entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.entry.bind("<Return>", lambda e: self.start_export())

        self.export_btn = ttk.Button(row, text="开始导出", command=self.start_export)
        self.export_btn.grid(row=0, column=2)

        outrow = ttk.Frame(pad)
        outrow.grid(row=4, column=0, sticky="ew", pady=(12, 8))
        outrow.grid_columnconfigure(1, weight=1)

        ttk.Label(outrow, text="输出目录：").grid(row=0, column=0, sticky="w")
        self.out_var = tk.StringVar(value=str(app_dir() / "exports"))
        ttk.Entry(outrow, textvariable=self.out_var).grid(
            row=0, column=1, sticky="ew", padx=(8, 8)
        )
        ttk.Button(outrow, text="选择", command=self.choose_out).grid(row=0, column=2)

        media_row = ttk.Frame(pad)
        media_row.grid(row=5, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(media_row, text="附带导出：").pack(side="left")

        self.images_var = tk.BooleanVar(value=True)
        self.files_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            media_row, text="图片", variable=self.images_var
        ).pack(side="left", padx=(6, 8))
        ttk.Checkbutton(
            media_row, text="文件", variable=self.files_var
        ).pack(side="left", padx=(0, 10))
        ttk.Label(
            media_row,
            text="仅导出微信本机仍有缓存的内容；Markdown 可直接预览图片、点击文件。",
        ).pack(side="left")

        ttk.Separator(pad).grid(row=6, column=0, sticky="ew", pady=10)

        self.status = tk.Text(
            pad,
            height=10,
            wrap="word",
            state="disabled",
        )
        self.status.grid(row=7, column=0, sticky="nsew")

        bottom = ttk.Frame(pad)
        bottom.grid(row=8, column=0, sticky="ew", pady=(10, 0))
        bottom.grid_columnconfigure(0, weight=1)

        self.open_btn = ttk.Button(
            bottom,
            text="打开导出文件夹",
            command=self.open_output,
            state="disabled",
        )
        self.open_btn.grid(row=0, column=1, sticky="e")

        self.entry.focus_set()
        self.after(100, self.poll_queue)

    def choose_out(self):
        path = filedialog.askdirectory(
            initialdir=self.out_var.get() or str(app_dir())
        )
        if path:
            self.out_var.set(path)

    def log(self, msg):
        self.status.configure(state="normal")
        self.status.insert("end", str(msg) + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    def start_export(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning(APP_TITLE, "请输入好友备注名、昵称或群名。")
            return

        if not is_wechat_running():
            self.log("未检测到正在运行的 Windows 微信。")
            messagebox.showwarning(
                APP_TITLE,
                "未检测到正在运行的 Windows 微信。\n\n"
                "请先启动并登录微信，保持微信在后台运行，然后重新开始导出。",
            )
            return

        self.export_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.last_output = None
        self.log("")
        self.log(f"开始导出：{name}")

        thread = threading.Thread(
            target=self.worker,
            args=(
                name,
                self.out_var.get().strip() or str(app_dir() / "exports"),
                self.images_var.get(),
                self.files_var.get(),
            ),
            daemon=True,
        )
        thread.start()

    def worker(self, name, outdir, export_images, export_files):
        try:
            result = export_chat(
                name,
                outdir,
                progress=lambda m: self.q.put(("log", m)),
                export_images=export_images,
                export_files=export_files,
            )
            self.q.put(("done", result))
        except Exception as e:
            self.q.put(("error", f"{type(e).__name__}: {e}"))

    def poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "done":
                    self.last_output = payload["output_dir"]
                    self.log(f"输出：{payload['output_dir']}")
                    self.export_btn.configure(state="normal")
                    self.open_btn.configure(state="normal")

                    stats = payload.get("media_stats") or {}
                    media_line = (
                        f"\n图片：{stats.get('images_exported', 0)}/"
                        f"{stats.get('images_requested', 0)}"
                        f"\n文件：{stats.get('files_exported', 0)}/"
                        f"{stats.get('files_requested', 0)}"
                    )

                    messagebox.showinfo(
                        APP_TITLE,
                        f"导出完成。\n\n"
                        f"类型：{'群聊' if payload['is_group'] else '私聊'}\n"
                        f"消息数：{payload['message_count']}\n"
                        f"会话：{payload['chat_name']}"
                        f"{media_line}\n\n"
                        "已生成 TXT、Markdown 和 JSON。",
                    )
                elif kind == "error":
                    self.export_btn.configure(state="normal")
                    self.log("导出失败：" + payload)
                    messagebox.showerror(
                        APP_TITLE,
                        "导出失败：\n\n" + payload,
                    )
        except queue.Empty:
            pass

        self.after(100, self.poll_queue)

    def open_output(self):
        if not self.last_output:
            return
        path = Path(self.last_output)
        if path.exists():
            os.startfile(str(path))


if __name__ == "__main__":
    App().mainloop()
