��            )         �  =   �     �     �          %     >     Q     m     �  "   �  �   �  �   f  �   �     �     �  8   �     �       1     I  M     �  @   �    �  �   �  �   �	     >
  .   [
  �   �
  �   ^  �   �  �  �  i   �  #     (   1  )   Z  .   �     �  4   �  =     +   F  U   r    �  �   �  D  �     �       g        �  .   �  O   �  3    3   H  �   |  p    �   r    i  6   �  O   �  H    �   P    :                                                             
                                                      	                     An upgrade from '%s' to '%s' is not supported with this tool. Broken packages Can not upgrade Can not write to '%s' Can't guess meta-package Can't install '%s' Continue running under SSH? Could not calculate the upgrade Custom servers Error authenticating some packages If you run a firewall, you may need to temporarily open this port. As this is potentially dangerous it's not done automatically. You can open the port with e.g.:
'%s' It was impossible to install a required package. Please report this as a bug using 'ubuntu-bug ubuntu-release-upgrader-core' in a terminal. It was not possible to authenticate some packages. This may be a transient network problem. You may want to try again later. See below for a list of unauthenticated packages. Main server Reading cache Remove package in bad state Remove packages in bad state Server for %s Starting additional sshd The essential package '%s' is marked for removal. The package '%s' is in an inconsistent state and needs to be reinstalled, but no archive can be found for it. Do you want to remove this package now to continue? The packages '%s' are in an inconsistent state and need to be reinstalled, but no archives can be found for them. Do you want to remove these packages now to continue? The server may be overloaded This is most likely a transient problem, please try again later. This session appears to be running under ssh. It is not recommended to perform a upgrade over ssh currently because in case of failure it is harder to recover.

If you continue, an additional ssh daemon will be started at port '%s'.
Do you want to continue? This usually means that another package management application (like apt-get or aptitude) already running. Please close that application first. To make recovery in case of failure easier, an additional sshd will be started on port '%s'. If anything goes wrong with the running ssh you can still connect to the additional one.
 Unable to get exclusive lock Upgrading over remote connection not supported You are running the upgrade over a remote ssh connection with a frontend that does not support this. Please try a text mode upgrade with 'do-release-upgrade'.

The upgrade will abort now. Please try without ssh. Your system contains broken packages that couldn't be fixed with this software. Please fix them first using synaptic or apt-get before proceeding. Your system does not contain a %s or %s package and it was not possible to detect which version of Ubuntu you are running.
 Please install one of the packages above first using synaptic or apt-get before proceeding. Project-Id-Version: ubuntu-release-upgrader
Report-Msgid-Bugs-To: sebastian.heinlein@web.de
PO-Revision-Date: 2014-08-21 06:20+0000
Last-Translator: FULL NAME <EMAIL@ADDRESS>
Language-Team: Chechen <ce@li.org>
Language: ce
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8
Content-Transfer-Encoding: 8bit
Plural-Forms: nplurals=2; plural=n != 1;
X-Launchpad-Export-Date: 2019-11-15 04:46+0000
X-Generator: Launchpad (build c597c3229eb023b1e626162d5947141bf7befb13)
 '%s'-гара '%s'-на долу цIиндар хIокху утилитица уьйр йолуш дац. Галайойлла пакеташ ЦIиндар кхочуш ца дало '%s' чохь дIаяздан йиш яц Оьшу мета-пакет ца карайо '%s' дIа ца хIоттало Кхин дIа а SSH гIоьнца бай болх? Системин цIиндарна хьесап ца дало Пайдаэцархойн сервераш Цхьайолу пакеташна аутентификаци ярехь гIалат Брандмауэр летта елахь, цхьана ханна и порт схьаелла езаш хила тарло. Иза кхераме хила тарлуш хиларна, порт ша схьаеллалуш яц. И схьаелла йиш ю иштта:
'%s' Оьшуш йолу пакет дIа ца хIоттало. Оцу гIалатах хаам бие, терминала чохь 'ubuntu-bug ubuntu-release-upgrader-core' команда кхочушдай. Цхьайолу пакеташна аутентификаци ца яло. И интернет галйалар бахьна долуш хила тарло, тIаьхьуо юха а хьажа мегар ду и кхочушдан. Лахахь аутентификаци янза йолу пакетийн цIераш ю. Коьрта сервер Кеш ешар ГIалаташ долу пакет дIаяккха ГIалаташ долу пакеташ дIаяха %s-на сервер ТIетоьхна йолу sshd йолош ю. '%s' коьрта пакеи дIаяккха билгалйаьккхина ю. ЦIинйеш йолу пакет '%s' дIахIоттор чекх ца даьккхина, иза юха дIахIотто еза. Амма цунна оьшуш йолу архив ца карайо. И пакет дIа а яккхий, кхин дIа хьой процесс? ЦIинйеш йолу пакеташ '%s' дIахIиттор чекх ца даьккхина, уьш юха дIахIитто еза. Амма царна оьшуш йолу архиваш ца карайо. И пакеташ дIа а яхий, кхин дIа хьой процесс? Сервер тIех юьзна хила тарло Иза цхьана ханна йолу проблема хила тарло, тIаьхуо юха кхочушдан хьажа и. ХIара сеанс ssh чохь йолийна ю. ssh гIоьнца цIиндар кхочуш ца дар гIоле ю, хIунда аьлча, цхьаъ галдалахь, юхаметтахIотто хала хир ду.

Болх кхин дIа беш белахь, ssh кхин гIуллакх '%s' портехь долор ду.
КхидIа яхийтий? Дукхахьолахь иза пакеташна урхалла ден кхин программа летта ю бохург ду (apt-get я aptitude, масала). Цкъа хьалха хIара программа дIакъовла еза. ГIалат даьлча, меттахIотто аттах хилийта, '%s' портехь sshd тIетуху гIуллакх латор ду. Пайдаоьцучу ssh-на цхьаъ хилахь, тIетуху гIуллакхна тIетасавала йиш хир ю.
 Эксклюзиве блок схьа ца эцало Генара тIетасарехула цIиндар кхочуш ца дало Хьо уьйр йоцучу клиентан ssh тIетасарехула цIиндар кхочушдан гIерташ ву. 'do-release-upgrade' гIоьнца текстан рожехь цIиндар кхочушде.

ЦIиндар сацийна. ssh тIетасарехула а доцуш кхин цкъа хьажа. ХIокху программе нислун йоцу галайойлла пакеташ ю системи чохь. Кхин дIа болх бале, synaptic я apt-get программийн гIоьнца дIанисйие уьш. Системи чохь %s я %s пакет яц, цундела Ubuntu летта йолу верси билгал ца яккхало.
Болх кхин дIа бале, synaptic я apt-get программийн гIоьнца оцу пакетех цхьаъ дIахIоттае. 