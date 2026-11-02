package controllers.battle.qc2
{
   import com.game.engine.animation.IAnimatable;
   import com.game.engine.core.GameFrame;
   import com.game.engine.utils.SimpleTextLog;
   import flash.display.Stage;
   import flash.display.Sprite;
   import flash.events.MouseEvent;
   import flash.net.URLLoader;
   import flash.net.URLRequest;
   import flash.text.TextField;
   import flash.text.TextFormat;
   import flash.utils.getQualifiedClassName;
   import models.managers.BattleModelManager;
   import models.managers.BuffModelManager;
   import models.managers.SoulStoneManager;
   import models.vo.BuffVO;
   import models.vo.UserVO;
   import models.vo.SkillConfigVO;
   import viewers.entitys.Entity;
   import viewers.entitys.man.RoleEntity;
   import viewers.entitys.man.MonsterEntity;

   import flash.events.KeyboardEvent;
   import flash.utils.setTimeout;
   import flash.utils.clearTimeout;
   import flash.events.Event;
   import flash.net.FileReference;
   import flash.net.FileFilter;
   import models.vo.RequestVO;
   import flash.text.TextFieldType;
   import flash.events.ThrottleEvent;
   import modules.ApplicationFacade;
   
   public class SimulateServerFrame implements IAnimatable
   {
       
      
      private var _keys:Array;
      
      private var _saveKeys:Array;
      
      private var _deleted:Boolean;
      
      private var k:int = 0;
      
      private var _testArr:Array;
      
      private var id:int;
      
      private var _lastDate:Date;
      
      private var _elapsedTime:Number = 0;
      
      private var _frameRate:Number = 0;
      
      private var _tempFrameRate:Number = 0;
      
      public var f:int;
      
      public var currThrottleState:String = "resume";
      
      public var currThrottleFrameRate:Number = 30;
      
      public var _throttleTime:Number = 0;
      
      private var stage:Stage;
      
      private var _frames:Array;
      
      private var _frameObj:Object;
      
      // Read-only state observation; never injects inputs or changes battle state.
      private static var observerStage:Stage;
      private static var observerLabel:TextField;
      private static var observerButton:Sprite;
      private static var observerEnabled:Boolean = true;
      private static var observerLoaders:Array = [];
      private var observerActive:Boolean = false;
      private var observerBatch:Array = [];
      private var observerLastFrame:int = -1;
      private var observerBatchId:int = 0;
      private var observerTotal:int = 0;
      private var observerSession:String;

      public static function installObserver(s:Stage) : void
      {
         if(s == null || observerStage != null) return;
         observerStage = s;
         observerLabel = new TextField();
         observerLabel.width = 480;
         observerLabel.height = 44;
         observerLabel.x = Math.max(8,s.stageWidth-488);
         observerLabel.y = 4;
         observerLabel.background = true;
         observerLabel.backgroundColor = 0x18212C;
         observerLabel.defaultTextFormat = new TextFormat("Microsoft YaHei",12,0xFFFFFF);
         observerLabel.mouseEnabled = false;
         observerLabel.selectable = false;
         s.addChild(observerLabel);
         observerButton = new Sprite();
         observerButton.x = Math.max(8,s.stageWidth-168);
         observerButton.y = 228;
         observerButton.buttonMode = true;
         observerButton.graphics.beginFill(0x275D88);
         observerButton.graphics.drawRoundRect(0,0,160,28,6,6);
         observerButton.graphics.endFill();
         var label:TextField = new TextField();
         label.defaultTextFormat = new TextFormat("Microsoft YaHei",13,0xFFFFFF,true);
         label.text = "暂停 / 恢复观察";
         label.x = 5;
         label.y = 3;
         label.width = 150;
         label.height = 24;
         label.mouseEnabled = false;
         label.selectable = false;
         observerButton.addChild(label);
         observerButton.addEventListener("click",toggleObserver);
         s.addChild(observerButton);
         showObserver("已开启：仅魔渊第九层；手动操作，不自动闪避或攻击");
         emitObserver({event:"observer_ready",version:2,build:"seed_bank_r2_right"});
         installSeedBank(s);
      }

      private static function toggleObserver(e:MouseEvent) : void
      {
         e.stopImmediatePropagation();
         if(seedBankPlaying || seedBankPending) return;
         observerEnabled = !observerEnabled;
         showObserver(observerEnabled ? "观察已恢复；操作完全由玩家控制" : "观察已暂停；操作完全由玩家控制");
         emitObserver({event:"observer_toggle",enabled:observerEnabled});
      }

      private static function showObserver(text:String) : void
      {
         if(observerLabel == null || observerStage == null) return;
         observerLabel.text = (seedBankStage != null ? seedBankHeading() : "魔渊JSON研究室 R2 / 本地回放") + "\n" + text;
         if(seedBankControls != null && seedBankControls.parent == observerStage) observerStage.setChildIndex(seedBankControls,observerStage.numChildren-1);
         if(observerLabel.parent == observerStage)
            observerStage.setChildIndex(observerLabel,observerStage.numChildren-1);
         if(observerButton != null && observerButton.parent == observerStage)
            observerStage.setChildIndex(observerButton,observerStage.numChildren-1);
      }

      private static function emitObserver(obj:Object) : void
      {
         try
         {
            if(observerLoaders.length >= 4) return;
            var request:URLRequest = new URLRequest("http://127.0.0.1:13080/observer/event");
            request.method = "POST";
            request.contentType = "application/json";
            request.data = JSON.stringify(obj);
            var loader:URLLoader = new URLLoader();
            observerLoaders.push(loader);
            loader.addEventListener("complete",onObserverReply);
            loader.addEventListener("ioError",onObserverReply);
            loader.addEventListener("securityError",onObserverReply);
            loader.load(request);
         }
         catch(error:Error)
         {
            trace("[BATTLE_OBSERVER] telemetry unavailable");
         }
      }

      private static function onObserverReply(e:Event) : void
      {
         var loader:URLLoader = e.currentTarget as URLLoader;
         var index:int = observerLoaders.indexOf(loader);
         if(index >= 0) observerLoaders.splice(index,1);
         loader.removeEventListener("complete",onObserverReply);
         loader.removeEventListener("ioError",onObserverReply);
         loader.removeEventListener("securityError",onObserverReply);
      }

      private function beginObserver() : void
      {
         var manager:BattleModelManager = BattleModelManager.getIns();
         if(manager.levelInfo == null || manager.levelInfo.id != 300109 || manager.levelParam == null ||
            manager.levelParam.isVideo || manager.levelParam.isMultiplayer) return;
         observerActive = true;
         observerSession = String(new Date().time);
         emitObserver({event:"battle_started",session:observerSession,dungeonId:300109,
                       mode:"observe_only",capturePhase:"before_local_frame_emit"});
         showObserver("已进入第九层：正在读取状态，请正常手动挑战");
      }

      private static function snapshotEntity(entity:RoleEntity) : Object
      {
         var vo:UserVO = entity.userVo;
         var state:Object = {entityId:entity.Id,charID:vo.charID,type:entity.getType(),
                             x:entity.position.x,y:entity.position.y,
                             direction:entity.direction,action:entity.currentActionState,
                             hp:vo.hp,mp:vo.mp,hpMax:vo.allhpMax,
                             dead:entity.isDie,hurting:entity.isHurting,
                             attacking:entity.getIsAttacking(),onGround:entity.onGround,
                             canManipulate:entity.canManipulate,canAttack:entity.canAttack};
         try { state.animationFrame = entity.getNowAnimationcurrentFrame(); }
         catch(error:Error) { state.animationFrame = null; }
         var skill:Object = entity.manConfigVo.skills[entity.currentActionState];
         state.skillId = skill is SkillConfigVO ? skill.id : null;
         var cd:Object = {};
         for(var key:String in vo.skillCD)
         {
            var value:Object = vo.skillCD[key];
            if(value is Number || value is int || value is uint || value is Boolean || value is String)
               cd[key] = value;
         }
         state.combatAttributes = {dodge:vo.alldodge,hit:vo.allhit,atk:vo.allatk,baseAtk:vo.atk,oldAtk:vo.oldAtk};
         state.dodgeNum = vo.dodgeNum; state.hurtNum = vo.hurtNum;
         state.fatherEntityId = vo.father != null ? vo.father.entitieId : null;
         state.skillCD = cd;
         var skillStates:Array = [];
         for(var actionKey:String in entity.manConfigVo.skills)
         {
            var configured:Object = entity.manConfigVo.skills[actionKey];
            if(configured is SkillConfigVO)
               skillStates.push({action:actionKey,id:configured.id,nowCD:configured.nowCD,cd:configured.cd});
         }
         state.skillCooldowns = skillStates;
         var buffs:Array = BuffModelManager.getIns().getManAllBuffsByEid(vo.entitieId);
         var out:Array = [];
         if(buffs != null)
         {
            for each(var buff:BuffVO in buffs)
            {
               if(buff != null && buff.config != null)
                  out.push({id:buff.config.id,time:buff.time,currTime:buff.currTime,
                            cd:buff.currCd,level:buff.level,value:buff.value});
            }
         }
         state.buffs = out;
         return state;
      }

      private function observeFrame() : void
      {
         if(!observerActive || !observerEnabled || observerLastFrame == this.f) return;
         observerLastFrame = this.f;
         try
         {
            var manager:BattleModelManager = BattleModelManager.getIns();
            var logic:BattleLogic = manager.levelParam.logic;
            var player:RoleEntity = null;
            if(logic.users.length > 0)
               player = manager.getPlayerByEntityId(logic.users[0].getCurrentUVO().entitieId) as RoleEntity;
            var record:Object = {inputFrame:this.f,logicFrame:QCOnServerFrame2.cliCurrFrame,
                                 player:player != null ? snapshotEntity(player) : null,monsters:[]};
            var candidates:Array = [];
            for each(var item:Entity in manager.entitys)
            {
               if(item is MonsterEntity && item.userVo != null)
               {
                  candidates.push(item.userVo.charID);
                  if(item.userVo.charID == 4279)
                     record.monsters.push(snapshotEntity(item as RoleEntity));
               }
            }
            if(record.monsters.length == 0) record.monsterCandidates = candidates;
            if(player != null)
            {
               var souls:Array = SoulStoneManager.getIns().getByPlayerId(player.Id);
               var soulStates:Array = [];
               for each(var soul:Object in souls)
                  soulStates.push({className:getQualifiedClassName(soul),cd:soul.cd,time:soul.time,value:soul.value});
               record.player.soulStates = soulStates;
            }
            observerBatch.push(record);
            observerTotal++;
            if(observerBatch.length >= 30) flushObserver();
            if(this.f % 30 == 0)
               showObserver("输入帧 " + this.f + " / 已处理逻辑帧 " + QCOnServerFrame2.cliCurrFrame +
                            "；Boss实体数 " + record.monsters.length + "；记录 " + observerTotal);
         }
         catch(error:Error)
         {
            observerActive = false;
            flushObserver();
            emitObserver({event:"observer_error",session:observerSession,frame:this.f,error:String(error)});
            showObserver("状态读取失败，已停止观察；游戏操作不受影响");
         }
      }

      private function flushObserver() : void
      {
         if(observerBatch.length == 0) return;
         emitObserver({event:"states",session:observerSession,batch:observerBatchId++,frames:observerBatch});
         observerBatch = [];
      }

      private function finishObserver() : void
      {
         if(observerSession == null) return;
         flushObserver();
         emitObserver({event:"battle_destroyed",session:observerSession,lastInputFrame:this.f,totalSamples:observerTotal});
         observerActive = false;
         observerSession = null;
         showObserver("本局观察结束；下一次进入第九层继续记录");
      }

      private static function readReplayState(frame:int) : Object
      {
            var manager:BattleModelManager = BattleModelManager.getIns();
            var logic:BattleLogic = manager.levelParam.logic;
            var player:RoleEntity = null;
            if(logic.users.length > 0)
               player = manager.getPlayerByEntityId(logic.users[0].getCurrentUVO().entitieId) as RoleEntity;
            var record:Object = {inputFrame:frame,logicFrame:QCOnServerFrame2.cliCurrFrame,
                                 player:player != null ? snapshotEntity(player) : null,monsters:[]};
            var candidates:Array = [];
            record.clones = [];
            for each(var item:Entity in manager.entitys)
            {
               if(item is RoleEntity && item.userVo != null && item.userVo.father != null)
                  record.clones.push(snapshotEntity(item as RoleEntity));
               if(item is MonsterEntity && item.userVo != null)
               {
                  candidates.push(item.userVo.charID);
                  if(item.userVo.charID == 4279)
                     record.monsters.push(snapshotEntity(item as RoleEntity));
               }
            }
            record.attackEvents = [];
            for each(var hit:Object in manager.getHurtManData())
            {
               if(hit != null && hit.attUserVo != null && hit.hurUserVo != null)
                  record.attackEvents.push({attacker:hit.attUserVo.entitieId,
                     target:hit.hurUserVo.entitieId,attackerChar:hit.attUserVo.charID,
                     targetChar:hit.hurUserVo.charID,damageType:hit.damageType,
                     damage:hit.damageValue,skillId:hit.attSkill != null ? hit.attSkill.id : null});
            }
            if(record.monsters.length == 0) record.monsterCandidates = candidates;
            if(player != null)
            {
               var souls:Array = SoulStoneManager.getIns().getByPlayerId(player.Id);
               var soulStates:Array = [];
               for each(var soul:Object in souls)
                  soulStates.push({className:getQualifiedClassName(soul),cd:soul.cd,time:soul.time,value:soul.value});
               record.player.soulStates = soulStates;
            }
         return record;
      }
      private static var replaySession:String;
      private static var replayReport:Object;
      private static var replayBatch:Array = [];
      private static var replayBatchId:int = 0;
      private static var replayLastFrame:int = -1;
      private static var replaySamples:int = 0;
      private static var replayBossRefs:Object = {};
      private static var replayPlayerRef:UserVO;
      private static var replayFinished:Boolean = false;
      private static var replayAssessment:Object;

      public static function beginReplayObservation(s:Stage) : void
      {
         installObserver(s);
         var manager:BattleModelManager = BattleModelManager.getIns();
         if(manager.levelInfo == null || manager.levelInfo.id != 300109 || manager.levelParam == null ||
            manager.levelParam.logic == null) return;
         replayReport = manager.levelParam.logic.report;
         researchQueueLoading = false;
         if(replayReport == null) return;
         replaySession = "replay_" + String(new Date().time);
         replayBatch = [];
         replayBatchId = 0;
         replayLastFrame = -1;
         replaySamples = 0;
         replayBossRefs = {};
         replayPlayerRef = null;
         replayFinished = false;
         replayAssessment = null;
         emitObserver({event:"battle_started",session:replaySession,dungeonId:300109,
                       mode:replayReport.lab != null ? replayReport.lab.mode : "replay_original",
                       reportId:replayReport.reportId,seed:replayReport.sceneInfo.randomSeed,
                       lab:replayReport.lab,capturePhase:"stage_after_logic_processing"});
         seedBankBegin(replayReport);
         showObserver(replayReport.lab != null ? "本地实验：你的属性＋源种子＋源操作；不提交成绩" : "正在观察榜首原生回放；不提交成绩");
      }

      private static function retainReplayReferences() : void
      {
         var manager:BattleModelManager = BattleModelManager.getIns();
         if(manager.levelParam == null || manager.levelParam.logic == null) return;
         var logic:BattleLogic = manager.levelParam.logic;
         if(logic.users.length > 0) replayPlayerRef = logic.users[0].getCurrentUVO();
         for each(var item:Entity in manager.entitys)
         {
            if(item is MonsterEntity && item.userVo != null && item.userVo.charID == 4279)
               replayBossRefs[String(item.Id)] = item.userVo;
         }
      }

      public static function observeReplayState(cursor:int) : void
      {
         researchProgressUpdate(QCOnServerFrame2.cliCurrFrame,replayFinished ? "本段已结束" : "播放中");
         if(replaySession == null || replayFinished || !observerEnabled) return;
         var frame:int = QCOnServerFrame2.cliCurrFrame;
         if(frame == replayLastFrame) return;
         replayLastFrame = frame;
         try
         {
            retainReplayReferences();
            var record:Object = readReplayState(frame);
            record.playbackCursor = cursor;
            if(researchOriginal != null && replayReport.lab != null && replayReport.lab.mode == "research_json_v1") { if(researchFrames.length < 6000) researchFrames.push(record); else researchTruncated = true; }
            replayBatch.push(record);
            replaySamples++;
            if(replayBatch.length >= 30) flushReplayBatch();
            if(frame % 30 == 0)
               showObserver("本地回放 / 逻辑帧 " + frame + "；Boss实体 " + record.monsters.length + "；样本 " + replaySamples);
            seedBankCheckDeath(record);
         }
         catch(error:Error)
         {
            flushReplayBatch();
            emitObserver({event:"observer_error",session:replaySession,frame:frame,error:String(error)});
            showObserver("回放状态读取失败；结果尚未确认");
         }
      }

      private static function flushReplayBatch() : void
      {
         if(replayBatch.length == 0) return;
         emitObserver({event:"states",session:replaySession,batch:replayBatchId++,frames:replayBatch});
         replayBatch = [];
      }

      public static function finishReplayObservation(reason:String) : Object
      {
         if(replaySession == null) return null;
         if(replayFinished) return replayAssessment;
         try
         {
            retainReplayReferences();
            var count:int = 0;
            var hp:Number = 0;
            var maxHp:Number = 0;
            for each(var boss:UserVO in replayBossRefs)
            {
               count++;
               hp += Math.max(0,boss.hp);
               maxHp += boss.allhpMax;
            }
            var playerHp:Number = replayPlayerRef != null ? replayPlayerRef.hp : -1;
            var known:Boolean = count > 0 && replayPlayerRef != null;
            var bossDead:Boolean = known && hp <= 0;
            var playerDead:Boolean = replayPlayerRef != null && playerHp <= 0;
            replayAssessment = {event:"replay_assessment",session:replaySession,reason:reason,
                                reportId:replayReport.reportId,lab:replayReport.lab != null,
                                logicFrame:QCOnServerFrame2.cliCurrFrame,bossCount:count,
                                bossHp:hp,bossHpMax:maxHp,bossHpRatio:maxHp > 0 ? hp/maxHp : null,
                                playerHp:playerHp,known:known,bossDead:bossDead,playerDead:playerDead,
                                win:known && bossDead && !playerDead,sourceEndFrame:PlayPvpVideoCmd.lastFrame,
                                capturePhase:"before_native_replay_result",scoreSubmitted:false};
            flushReplayBatch();
            emitObserver(replayAssessment);
            emitObserver({event:"battle_destroyed",session:replaySession,lastInputFrame:QCOnServerFrame2.cliCurrFrame,totalSamples:replaySamples});
            replayFinished = true;
            showObserver(known ? "本地观察结果：Boss HP " + hp + "，玩家 HP " + playerHp + "；不提交成绩" : "实验结束：未识别完整战斗实体，不能判定胜负");
            return replayAssessment;
         }
         catch(error:Error)
         {
            emitObserver({event:"observer_error",session:replaySession,error:String(error),phase:"finalize"});
            return null;
         }
      }

      public static function prepareReplayResult(report:Object) : void
      {
         var assessment:Object = finishReplayObservation("native_replay_complete");
         if(report == null || report.lab == null || assessment == null) return;
         // Local experiment UI only. No actual challenge or settlement is constructed.
         if(report.lab.mode == "seed_bank_v1" || report.lab.mode == "research_json_v1") PlayPvpVideoCmd.lastFrame = int(assessment.logicFrame);
         report.sceneInfo.score = 0;
         if(report.playerResult != null && report.playerResult.length > 0)
         {
            report.playerResult[0].result = assessment.win ? 5 : 0;
            report.playerResult[0].bossHp = assessment.bossHpRatio;
            report.playerResult[0].param = "local_observed_result";
            report.playerResult[0].life = assessment.playerHp;
         }
      }

      private static var seedBankSamples:Array = [];
      private static var seedBankOwner:String = "research_json";
      private static var seedBankStage:Stage;
      private static var seedBankControls:Sprite;
      private static var seedBankHotkeys:Object = {};
      private static var seedBankSelected:int = 0;
      private static var seedBankCurrent:int = -1;
      private static var seedBankPlaying:Boolean = false;
      private static var seedBankPending:Boolean = false;
      private static var seedBankAuto:Boolean = false;
      private static var seedBankHadBatch:Boolean = false;
      private static var seedBankCancelled:Boolean = false;
      private static var seedBankQueue:Array = [];
      private static var seedBankRows:Array = [];
      private static var seedBankBatchId:String;
      private static var seedBankNextTimer:uint = 0;
      private static var seedBankWatchdog:uint = 0;
      private static var seedBankLastFinished:String;

      public static function installSeedBank(s:Stage) : void
      {
         installResearchRoom(s);
      }

      private static function seedBankLayout(e:Event) : void
      {
         if(seedBankStage == null) return;
         var xpos:Number = Math.max(8,seedBankStage.stageWidth-488);
         if(observerLabel != null) { observerLabel.x = xpos; observerLabel.width = 480; }
         if(seedBankControls != null) { seedBankControls.x = xpos; seedBankControls.y = 52; }
         if(observerButton != null) { observerButton.x = xpos+320; observerButton.y = 228; }
      }

      private static function addSeedBankButton(text:String,code:int,xpos:int) : void
      {
         var button:Sprite = new Sprite();
         button.name = String(code); button.x = xpos; button.buttonMode = true;
         button.graphics.beginFill(code == 120 ? 0xA83232 : 0x275D88);
         button.graphics.drawRoundRect(0,0,114,28,6,6); button.graphics.endFill();
         var label:TextField = new TextField();
         label.defaultTextFormat = new TextFormat("Microsoft YaHei",12,0xFFFFFF,true);
         label.text = text; label.x = 4; label.y = 3; label.width = 108; label.height = 24;
         label.mouseEnabled = false; label.selectable = false;
         button.addChild(label); button.addEventListener("click",onSeedBankClick);
         seedBankControls.addChild(button);
      }

      private static function seedBankHeading() : String
      {
         var selected:Object = seedBankSamples[seedBankSelected];
         var text:String = "种子对照 " + (seedBankSelected+1) + "/" + seedBankSamples.length +
            " / " + selected.name + " / 种子 " + selected.seed;
         if(seedBankPlaying && seedBankCurrent >= 0)
            text += " / 正在播放：" + seedBankSamples[seedBankCurrent].name;
         if(seedBankAuto) text += " / 全部连测，剩余 " + seedBankQueue.length;
         return "PAIR R3 / " + text;
      }

      private static function onSeedBankClick(e:MouseEvent) : void
      {
         e.stopImmediatePropagation(); seedBankCommand(int(e.currentTarget.name));
      }
      private static function onSeedBankDeactivate(e:Event) : void { seedBankHotkeys = {}; }
      private static function onSeedBankKeyUp(e:KeyboardEvent) : void
      {
         if(e.keyCode < 117 || e.keyCode > 120) return;
         e.preventDefault(); e.stopImmediatePropagation();
         delete seedBankHotkeys[String(e.keyCode)];
      }
      private static function onSeedBankKey(e:KeyboardEvent) : void
      {
         if(e.keyCode < 117 || e.keyCode > 120) return;
         e.preventDefault(); e.stopImmediatePropagation();
         if(seedBankHotkeys[String(e.keyCode)]) return;
         seedBankHotkeys[String(e.keyCode)] = true; seedBankCommand(int(e.keyCode));
      }

      private static function seedBankCommand(code:int) : void
      {
         if(code == 120)
         {
            seedBankAuto = false; seedBankCancelled = true; seedBankQueue = [];
            if(seedBankNextTimer != 0)
            {
               clearTimeout(seedBankNextTimer); seedBankNextTimer = 0; seedBankPending = false;
            }
            emitObserver({event:"seed_bank_stop_requested",batchId:seedBankBatchId,playing:seedBankPlaying});
            showObserver(seedBankPlaying || seedBankPending ? "已取消后续连测；当前回放结束后停止" : "连测已停止");
            return;
         }
         if(code == 117)
         {
            if(seedBankAuto || seedBankPending) { showObserver("连测或加载中，请先用F9停止后再切换"); return; }
            seedBankSelected = (seedBankSelected+1) % seedBankSamples.length;
            emitObserver({event:"seed_bank_selected",index:seedBankSelected,sample:seedBankSamples[seedBankSelected]});
            showObserver(seedBankPlaying ? "已选择下一局；当前回放的种子保持原样" : "F7测试当前候选，F8依次测试全部候选");
            return;
         }
         if(seedBankPlaying || seedBankPending) { showObserver("当前回放或加载尚未结束"); return; }
         seedBankCancelled = false; seedBankRows = [];
         seedBankBatchId = "seedbank_" + String(new Date().time);
         seedBankQueue = [];
         seedBankAuto = code == 119; seedBankHadBatch = seedBankAuto;
         if(seedBankAuto)
         {
            for(var i:int = 1; i < seedBankSamples.length; i++)
               seedBankQueue.push((seedBankSelected+i) % seedBankSamples.length);
            emitObserver({event:"seed_bank_batch_started",batchId:seedBankBatchId,
               count:seedBankSamples.length,startIndex:seedBankSelected,ownerFingerprint:seedBankOwner});
         }
         seedBankLaunch();
      }

      public static function seedBankResolveCode(requested:String) : String
      {
         if(seedBankStage == null || requested == null || requested.indexOf("zhuxie_") != 0) return requested;
         return String(seedBankSamples[seedBankSelected].reportId);
      }

      private static function seedBankLaunch() : void
      {
         seedBankNextTimer = 0;
         if(seedBankPlaying) return;
         seedBankPending = true;
         if(seedBankWatchdog != 0) clearTimeout(seedBankWatchdog);
         seedBankWatchdog = setTimeout(seedBankTimeout,60000);
         emitObserver({event:"seed_bank_launch",batchId:seedBankBatchId,index:seedBankSelected,
            sample:seedBankSamples[seedBankSelected]});
         showObserver("正在加载候选；只运行本地保存录像");
         ApplicationFacade.getInstance().sendNotification("CMD_PLAY_VIDEO",{
            code:seedBankSamples[seedBankSelected].reportId});
      }

      public static function seedBankBegin(report:Object) : void
      {
         if(report == null || report.lab == null || report.lab.mode != "seed_bank_v1") return;
         var index:int = int(report.lab.caseIndex);
         if(index < 0 || index >= seedBankSamples.length || report.lab.ownerFingerprint != seedBankOwner)
         {
            seedBankTimeout(); return;
         }
         observerEnabled = true;
         seedBankPending = false; seedBankPlaying = true; seedBankCurrent = index;
         if(seedBankWatchdog != 0) clearTimeout(seedBankWatchdog);
         seedBankWatchdog = setTimeout(seedBankTimeout,60000);
         emitObserver({event:"seed_bank_case_started",batchId:seedBankBatchId,session:replaySession,
            index:index,sample:seedBankSamples[index],ownerFingerprint:seedBankOwner});
      }

      private static function seedBankTimeout() : void
      {
         seedBankWatchdog = 0;
         seedBankAuto = false; seedBankQueue = []; seedBankPending = false;
         if(seedBankNextTimer != 0) clearTimeout(seedBankNextTimer);
         seedBankNextTimer = 0;
         emitObserver({event:"seed_bank_timeout",batchId:seedBankBatchId,index:seedBankSelected,
            playing:seedBankPlaying,results:seedBankRows});
         showObserver("加载或回放超过60秒，连测已停止；当前结果不能判定为有效完成");
      }

      public static function seedBankCheckDeath(record:Object) : void
      {
         if(!seedBankPlaying || replayFinished || replayReport == null || replayReport.lab == null ||
            replayReport.lab.mode != "seed_bank_v1") return;
         if(record.player != null && (record.player.dead || record.player.hp <= 0))
         {
            replayReport.lab.actualDeathFrame = record.logicFrame;
            BattleModelManager.getIns().levelParam.logic.playVideoComplete();
         }
      }

      public static function seedBankAfterComplete(report:Object) : Boolean
      {
         if(report == null || report.lab == null || report.lab.mode != "seed_bank_v1") return false;
         if(seedBankLastFinished == replaySession) return true;
         seedBankLastFinished = replaySession;
         if(seedBankWatchdog != 0) clearTimeout(seedBankWatchdog);
         seedBankWatchdog = 0; seedBankPlaying = false; seedBankPending = false;
         var index:int = int(report.lab.caseIndex);
         var assessment:Object = replayAssessment;
         var row:Object = {event:"seed_bank_case_result",batchId:seedBankBatchId,session:replaySession,
            index:index,name:seedBankSamples[index].name,seed:seedBankSamples[index].seed,
            ownerFingerprint:seedBankOwner,assessment:assessment,actualDeathFrame:report.lab.actualDeathFrame};
         seedBankRows.push(row); emitObserver(row);
         if(seedBankAuto && seedBankQueue.length > 0)
         {
            seedBankSelected = int(seedBankQueue.shift()); seedBankPending = true;
            showObserver("本轮已记录，1.2秒后自动加载下一候选");
            seedBankNextTimer = setTimeout(seedBankLaunch,1200);
            return true;
         }
         if(seedBankHadBatch)
         {
            seedBankHadBatch = false; seedBankAuto = false;
            emitObserver({event:"seed_bank_batch_complete",batchId:seedBankBatchId,
               cancelled:seedBankCancelled,count:seedBankRows.length,results:seedBankRows});
         }
         showObserver("测试结束，已记录" + seedBankRows.length + "份；可F6切换、F7单测、F8全测");
         return false;
      }

      private static var researchStage:Stage;
      private static var researchFile:FileReference;
      private static var researchOriginal:Object;
      private static var researchFrames:Array = [];
      private static var researchTruncated:Boolean = false;
      private static var researchControls:Sprite;

      public static function installResearchRoom(s:Stage) : void
      {
         if(s == null || researchStage != null) return;
         researchStage = s;
         researchControls = new Sprite();
         researchControls.x = Math.max(8,s.stageWidth - 488);
         researchControls.y = 52;
         s.addChild(researchControls);
         researchButton("导入回放/实战JSON",0,"import");
         researchButton("导出本场结果",160,"save");
         researchButton("研究室：收起",320,"hide");
         researchButton("批量读取榜单",0,"batch",34);
         researchButton("回放连测开关",160,"queue_auto",34);
         researchButton("下一份回放",320,"queue_next",34);
         researchButton("导出批量结果",0,"queue_save",68);
         researchButton("读取自身快照",160,"snapshot_read",68);
         researchButton("导出自身快照",320,"snapshot_save",68);
         researchButton("停止录制并松键",0,"manual_stop",102);
         researchButton("保留并导出本次",160,"manual_keep",102);
         researchButton("丢弃本次录像",320,"manual_discard",102);
         researchManualStatus = new TextField();
         researchManualStatus.defaultTextFormat = new TextFormat("Microsoft YaHei",12,0xFFFFFF);
         researchManualStatus.background = true; researchManualStatus.backgroundColor = 0x18212C;
         researchManualStatus.width = 476; researchManualStatus.height = 64; researchManualStatus.y = 136;
         researchManualStatus.wordWrap = true; researchControls.addChild(researchManualStatus);
         researchManualMessage("手动录制：进入魔渊第九层自动临时记录，默认不保留。");
         researchButton("实战：持续预备/取消",0,"live_arm",204);
         researchButton("实战急停",160,"live_stop",204);
         researchButton("自动重新挑战开关",320,"live_retry",204);
         researchInstallProgress(s);
         s.addEventListener(KeyboardEvent.KEY_DOWN,onResearchQueueKey);
         showObserver("JSON研究室：导入本地录像，由原生引擎运行；不提交成绩");
      }

      private static function researchButton(labelText:String,xpos:int,kind:String,ypos:int = 0,target:Sprite = null) : void
      {
         var button:Sprite = new Sprite();
         button.x = xpos; button.y = ypos; button.name = kind; button.buttonMode = true;
         button.graphics.beginFill(0x275D88);
         button.graphics.drawRoundRect(0,0,152,28,6,6);
         button.graphics.endFill();
         var label:TextField = new TextField();
         label.defaultTextFormat = new TextFormat("Microsoft YaHei",12,0xFFFFFF,true);
         label.text = labelText; label.width = 148; label.height = 24;
         label.x = 4; label.y = 3; label.mouseEnabled = false;
         button.addChild(label); button.addEventListener(MouseEvent.CLICK,onResearchClick);
         (target != null ? target : researchControls).addChild(button);
      }

      private static function onResearchClick(e:MouseEvent) : void
      {
         e.stopImmediatePropagation();
         var kind:String = e.currentTarget.name;
         if(kind == "live_arm") { if(macroSamples.length == 0) { showObserver("请先导入网页导出的实战操作JSON"); return; } handleMacroCommand(119); return; }
         if(kind == "live_retry") { handleMacroCommand(118); return; }
         if(kind == "live_stop") { handleMacroCommand(120); return; }
         if(researchManualCommand(kind)) return;
         if(researchBatchCommand(kind)) return;
         if(kind == "hide")
         {
            var visible:Boolean = !researchControls.getChildAt(0).visible;
            for(var n:int = 0; n < researchControls.numChildren; n++) if(n != 2) researchControls.getChildAt(n).visible = visible;
            if(researchBatchPanel != null) researchBatchPanel.visible = visible && researchBatchPanel.visible;
            return;
         }
         if(kind == "save")
         {
            if(researchOriginal == null || replayAssessment == null || !replayFinished || replayReport == null ||
               replayReport.lab == null || replayReport.lab.mode != "research_json_v1")
            {
               showObserver("尚无已完成的本地回放结果，不能把未完成记作失败");
               return;
            }
            var result:Object = {format:"zm4-research-result-v1",clientVersion:5870,
               input:researchOriginal,assessment:replayAssessment,states:researchFrames,
               truncated:researchTruncated,scoreSubmitted:false};
            researchFile = new FileReference();
            researchFile.save(JSON.stringify(result),"zm4_research_result.json");
            return;
         }
         var manager:BattleModelManager = BattleModelManager.getIns();
         if(researchQueueLoading || (manager.levelParam != null && manager.levelParam.isVideo && researchOriginal != null && !replayFinished))
         { showObserver("当前研究回放正在加载或运行，请完成后再导入"); return; }
         if(manager.levelParam != null && manager.levelParam.logic != null && !manager.levelParam.isVideo && macroResearchBattleActive(manager))
         {
            showObserver("请先退出当前实战、回到主城后再导入研究JSON");
            return;
         }
         researchFile = new FileReference();
         researchFile.addEventListener(Event.SELECT,onResearchSelected);
         researchFile.addEventListener(Event.COMPLETE,onResearchLoaded);
         researchFile.browse([new FileFilter("JSON回放","*.json")]);
      }

      private static function macroResearchBattleActive(manager:BattleModelManager) : Boolean
      {
         return !models.GameData.playerIsInTown && manager.levelInfo != null && manager.levelInfo.id == 300109;
      }

      private static function onResearchSelected(e:Event) : void
      {
         researchFile.load();
      }

      private static function onResearchLoaded(e:Event) : void
      {
         try
         {
            var text:String = researchFile.data.toString();
            if(text.charCodeAt(0) == 65279) text = text.substr(1);
            var input:Object = JSON.parse(text);
            if(input.format == "zm4-live-input-v1") { researchLoadLive(input); return; }
            researchImportQueue(input);
         }
         catch(error:Error)
         {
            showObserver("研究室导入失败：" + String(error));
         }
      }

      private static function researchRunResponse(input:Object) : void
      {
         try
         {
            var response:Object = JSON.parse(JSON.stringify(input.response != null ? input.response : input));
            if(response.report == null && response.sceneInfo != null) response = {code:200,report:response};
            var report:Object = response.report;
            if(report == null || int(report.copyId) != 300109 || report.sceneInfo == null ||
               report.sceneInfo.playerInfos == null || report.sceneInfo.playerInfos.length != 1 ||
               report.sceneInfo.playerInfos[0].p1 == null || report.sceneInfo.playerInfos[0].p1.equipments == null ||
               report.frames == null || report.frames.length == 0 || report.playerResult == null || report.playerResult.length == 0)
               throw new Error("需要本期魔渊第九层、单人完整回放");
            if(report.cg == null || String(report.cg).length == 0) throw new Error("缺少原始配置版本路径cg");
            if(report.sceneInfo.randomSeed == null || isNaN(Number(report.sceneInfo.randomSeed)) ||
               Number(report.sceneInfo.randomSeed) != int(report.sceneInfo.randomSeed)) throw new Error("缺少有效32位整数种子");
            researchOriginal = JSON.parse(JSON.stringify(response));
            researchFrames = []; researchTruncated = false;
            report.lab = {mode:"research_json_v1",sourceReportId:report.reportId,
               sourceResult:JSON.parse(JSON.stringify(report.playerResult)),runtimeValidated:false};
            report.sceneInfo.score = 0;
            report.playerResult[0].result = 0;
            report.playerResult[0].bossHp = 1;
            report.playerResult[0].life = 0;
            report.playerResult[0].param = "local_unverified";
            researchQueueLoading = true;
            researchProgressPrepare(input,report);
            ApplicationFacade.getInstance().sendNotification("CMD_PLAY_VIDEO",{localResponse:response});
         }
         catch(error:Error)
         {
            researchQueueAuto = false;
            researchQueueLoading = false;
            researchProgressUpdate(0,"加载失败");
            showObserver("研究室导入失败：" + String(error));
         }
      }

      private static var researchBatchPanel:Sprite;
      private static var researchBatchMode:String = "count";
      private static var researchBatchFields:Object = {};
      private static var researchBatchBusy:Boolean = false;
      private static var researchBatchGeneration:int = 0;
      private static var researchBatchTimer:uint = 0;
      private static var researchBatchConfig:Object;
      private static var researchBatchPage:int = 1;
      private static var researchBatchSeen:Object = {};
      private static var researchBatchSeenCount:int = 0;
      private static var researchBatchPending:Array = [];
      private static var researchBatchReports:Array = [];
      private static var researchBatchFailures:Array = [];
      private static var researchBatchExhausted:Boolean = false;
      private static var researchBatchReason:String = "not_started";
      private static var researchBatchMax:int = 0;
      private static var researchQueue:Array = [];
      private static var researchQueueIndex:int = -1;
      private static var researchQueueAuto:Boolean = false;
      private static var researchQueueResults:Array = [];
      private static var researchQueueRecorded:int = -1;
      private static var researchQueueLoading:Boolean = false;
      private static var researchOwnSnapshot:Object;
      private static var researchSnapshotBusy:Boolean = false;

      private static function onResearchQueueKey(e:KeyboardEvent) : void
      {
         if(e.keyCode == 120)
         {
            researchQueueAuto = false;
            showObserver("已停止后续本地连测，当前回放可继续");
         }
      }

      private static function researchBatchCommand(kind:String) : Boolean
      {
         if(kind == "snapshot_read") { researchReadOwnSnapshot(); return true; }
         if(kind == "snapshot_save")
         {
            if(researchOwnSnapshot == null) { showObserver("未捕获登录快照，请重新进入存档。换装或切心法后也需重新进入"); return true; }
            if(researchOwnSnapshot.panelAtRead == null) { showObserver("请先点击读取自身快照并核对原生面板，再导出"); return true; }
            if(researchOwnSnapshot.contextStatus == "sword_context_missing") { showObserver("剑意上下文未读取，暂不导出缺失配置；请打开自身背包后重新读取"); return true; }
            researchFile = new FileReference();
            researchFile.save(JSON.stringify(researchOwnSnapshot),"zm4_own_snapshot.json");
            return true;
         }
         if(kind == "batch")
         {
            if(researchBatchPanel == null) researchBuildBatchPanel();
            else researchBatchPanel.visible = !researchBatchPanel.visible;
            return true;
         }
         if(kind == "batch_mode")
         {
            researchBatchMode = researchBatchMode == "count" ? "range" : "count";
            showObserver(researchBatchMode == "count" ? "读取模式：前N份（20—100份，不是前N名）" : "读取模式：名次区间，包含边界同名次所有记录");
            return true;
         }
         if(kind == "batch_start") { researchStartBatch(); return true; }
         if(kind == "batch_stop")
         {
            researchBatchGeneration++; researchBatchBusy = false;
            if(researchBatchTimer != 0) clearTimeout(researchBatchTimer);
            researchBatchReason = "user_stopped";
            showObserver("已停止后续读取，保留" + researchBatchReports.length + "份，可导出部分结果");
            return true;
         }
         if(kind == "batch_save")
         {
            if(researchBatchConfig == null) { showObserver("请先读取榜单"); return true; }
            researchFile = new FileReference();
            researchFile.save(JSON.stringify({format:"zm4-replay-bundle-v1",clientVersion:5870,
               request:researchBatchConfig,capturedAtMs:new Date().time,complete:researchBatchReason == "target_reached" || researchBatchReason == "range_or_board_exhausted",
               stopReason:researchBatchReason,reports:researchBatchReports,failures:researchBatchFailures,
               maxCount:researchBatchMax}),"zm4_replay_bundle.json");
            return true;
         }
         if(kind == "queue_auto")
         {
            researchQueueAuto = !researchQueueAuto;
            showObserver(researchQueueAuto ? "本地回放连测已开启；F9停止，不执行真实挑战" : "本地回放连测已关闭");
            if(researchQueueAuto && replayFinished && researchQueueIndex + 1 < researchQueue.length) researchNextQueue();
            return true;
         }
         if(kind == "queue_next") { researchNextQueue(); return true; }
         if(kind == "queue_save")
         {
            researchFile = new FileReference();
            researchFile.save(JSON.stringify({format:"zm4-research-batch-results-v1",clientVersion:5870,
               total:researchQueue.length,completed:researchQueueResults.length,results:researchQueueResults,
               scoreSubmitted:false}),"zm4_batch_results.json");
            return true;
         }
         return false;
      }

      private static function researchMergeSnapshotContext(source:Object) : void
      {
         if(researchOwnSnapshot == null || source == null) return;
         var p:Object = researchOwnSnapshot.wrapper.p1;
         for each(var key:String in ["swordYi","sword","swordShi"])
         {
            if(source[key] == null || source[key] is Boolean) continue;
            var value:Object = source[key];
            if(value.hasOwnProperty("p1")) value = value.p1;
            if(value != null && !(value is Boolean)) p[key] = JSON.parse(JSON.stringify(value));
         }
      }

      public static function researchCaptureLoginSnapshot(route:String, reply:Object) : void
      {
         if(route == "connector.entryHandler.entry") { researchOwnSnapshot = null; return; }
         if(reply == null || reply.code != 200) return;
         if(route != "scene.playerHandler.enterScene")
         {
            if(researchOwnSnapshot != null)
            {
               var extra:Object = reply.curRecord != null ? reply.curRecord : reply;
               if(extra.rid == null || String(extra.rid) == String(researchOwnSnapshot.wrapper.rid)) researchMergeSnapshotContext(extra);
            }
            return;
         }
         researchOwnSnapshot = null;
         try
         {
            var record:Object = reply.curRecord;
            var user:Object = reply.user;
            if(record == null || user == null || record.p1 == null || record.userId == null || record._id == null ||
               user.name == null || user.vipLevel == null || Number(record.userId) != Number(user._id)) return;
            researchOwnSnapshot = {format:"zm4-own-snapshot-v1",capturedAtMs:new Date().time,
               wrapper:{uid:record.userId,playerId:record.userId,rid:record._id,name:user.name,vipLevel:user.vipLevel,
                  p1:JSON.parse(JSON.stringify(record.p1))},sourceRoute:"scene.playerHandler.enterScene",
               captureMode:"normal_login_response_plus_context",contextStatus:"awaiting_read",
               refreshHint:"换装或切换心法后退出存档再进入，重新捕获；读取后核对原生面板"};
            researchMergeSnapshotContext(record);
         }
         catch(error:Error) { researchOwnSnapshot = null; }
      }

      private static function researchReadOwnSnapshot() : void
      {
         if(researchOwnSnapshot == null)
         {
            showObserver("未捕获登录快照：请使用本版主文件重新进入存档；不会重复发送登录请求");
            return;
         }
         if(!models.GameData.playerIsInTown) { showObserver("请回主城读取并核对人物面板"); return; }
         try
         {
            var info:Object = models.managers.UserModelManager.getIns().getCurretPlayerInfo();
            if(info == null || Number(info.userId) != Number(researchOwnSnapshot.wrapper.uid)) throw new Error("当前人物身份与登录快照不一致，请重新进入存档");
            var p:Object = researchOwnSnapshot.wrapper.p1;
            if(models.managers.ClickRoleHead.pNum == 1)
            {
               var yi:Object = modules.sword.model.SwordModelManager.getIns().getSwordYi();
               if(yi != null && !(yi is Boolean) && (yi.hasOwnProperty("lv") || yi.hasOwnProperty("attr"))) p.swordYi = JSON.parse(JSON.stringify(yi));
               var sword:Object = modules.sword.model.SwordModelManager.getIns().body;
               if(sword != null && sword.p1 != null) p.sword = JSON.parse(JSON.stringify(sword.p1));
               var shi:Object = modules.sword.model.SwordModelManager.getIns().getSwordShi();
               if(shi != null && !(shi is Boolean)) p.swordShi = JSON.parse(JSON.stringify(shi));
            }
            var u:UserVO = info.p1;
            if(int(p.professionType) == 2) u = info.p1.children;
            if(u == null) throw new Error("当前心法人物尚未初始化");
            researchOwnSnapshot.panelAtRead = {capturedAtMs:new Date().time,heart:p.professionType,
               hpMax:u.allhpMax,mpMax:u.allmpMax,atk:u.allatk,phyDef:u.allphyDef,hit:u.allhit,dodge:u.alldodge,
               critical:u.allcritical,toughness:u.alltoughness,soulCritical:u.allsoulCritical,
               soulToughness:u.allsoulToughness,soulAtk:u.allsoulAtk,soulPhydef:u.allsoulPhydef};
            researchOwnSnapshot.contextStatus = p.swordYi != null ? "sword_context_present_panel_captured" : "sword_context_missing";
            showObserver("快照：生命" + u.allhpMax + " 攻击" + u.allatk + " 魔法" + u.allmpMax + " 闪避" + (u.alldodge * 100).toFixed(2) +
               "%；剑意" + (p.swordYi != null ? "已附带" : "未读取，请先打开自身背包后重试") + "。核对面板后导出；换装仍需重新进入存档。");
         }
         catch(error:Error) { showObserver("读取快照上下文失败：" + String(error)); }
      }

      private static function researchBuildBatchPanel() : void
      {
         researchBatchPanel = new Sprite();
         researchBatchPanel.graphics.beginFill(0x18212C,0.96);
         researchBatchPanel.graphics.drawRect(0,0,480,180); researchBatchPanel.graphics.endFill();
         researchBatchPanel.x = Math.max(8,researchStage.stageWidth - 488); researchBatchPanel.y = 280;
         researchStage.addChild(researchBatchPanel);
         researchField("activity","期数", "4",0,0);
         researchField("role","角色1—7", "1",160,0);
         researchButton("切换份数/名次",320,"batch_mode",0,researchBatchPanel);
         researchField("count","份数20—100","50",0,36);
         researchField("start","起始名次","1",160,36);
         researchField("end","结束名次","100",320,36);
         researchButton("开始读取",0,"batch_start",76,researchBatchPanel);
         researchButton("停止读取",160,"batch_stop",76,researchBatchPanel);
         researchButton("导出录像包",320,"batch_save",76,researchBatchPanel);
         var legend:TextField = new TextField();
         legend.defaultTextFormat = new TextFormat("Microsoft YaHei",12,0xFFFFFF);
         legend.width = 476; legend.height = 65; legend.y = 110;
         legend.text = "角色：1悟空 2唐僧 3八戒 4沙僧 5小白龙 6玉兔 7哪吒\n默认前50份；切换名次模式后读取起止名次（含并列）。\n读取完再点导出。仅查询榜单和录像，不挑战、不消费。";
         researchBatchPanel.addChild(legend);
      }

      private static function researchField(key:String,labelText:String,value:String,xpos:int,ypos:int) : void
      {
         var label:TextField = new TextField();
         label.defaultTextFormat = new TextFormat("Microsoft YaHei",12,0xFFFFFF);
         label.text = labelText; label.width = 90; label.height = 28; label.x = xpos; label.y = ypos;
         researchBatchPanel.addChild(label);
         var field:TextField = new TextField();
         field.type = TextFieldType.INPUT; field.restrict = "0-9"; field.background = true;
         field.backgroundColor = 0xFFFFFF; field.textColor = 0; field.border = true;
         field.width = 55; field.height = 26; field.x = xpos + 94; field.y = ypos;
         field.text = value; researchBatchPanel.addChild(field); researchBatchFields[key] = field;
      }

      private static function researchStartBatch() : void
      {
         if(researchBatchBusy) { showObserver("正在读取，请等待或停止当前任务"); return; }
         var manager:BattleModelManager = BattleModelManager.getIns();
         if(!models.GameData.playerIsInTown) { showObserver("请先退出副本或回放，回到主城后再批量读取榜单"); return; }
         var activity:int = int(researchBatchFields.activity.text);
         var role:int = int(researchBatchFields.role.text);
         var count:int = int(researchBatchFields.count.text);
         var start:int = int(researchBatchFields.start.text);
         var end:int = int(researchBatchFields.end.text);
         if(activity < 1 || role < 1 || role > 7 || (researchBatchMode == "count" && (count < 20 || count > 100)) ||
            (researchBatchMode == "range" && (start < 1 || end < start || end > 100)))
         { showObserver("参数错误：期数>=1，角色1—7；份数20—100，或名次1—100"); return; }
         researchBatchConfig = {activity:activity,role:role,mode:researchBatchMode,count:count,startRank:start,endRank:end};
         researchBatchGeneration++; researchBatchBusy = true; researchBatchPage = 1;
         researchBatchSeen = {}; researchBatchSeenCount = 0; researchBatchPending = [];
         researchBatchReports = []; researchBatchFailures = []; researchBatchExhausted = false;
         researchBatchReason = "running"; researchBatchMax = 0;
         researchReadRankPage();
      }

      private static function researchRequest(route:String,payload:Object,callback:Function) : void
      {
         var generation:int = researchBatchGeneration;
         var completed:Boolean = false;
         var timer:uint = 0;
         var done:Function = function(reply:Object):void
         {
            if(completed || generation != researchBatchGeneration || !researchBatchBusy) return;
            completed = true; clearTimeout(timer); researchBatchTimer = 0;
            try { callback(reply); }
            catch(error:Error) { researchBatchFailures.push({route:route,error:String(error)}); researchFinishBatch("server_error"); }
         };
         var request:RequestVO = new RequestVO(route,payload,done);
         request.allwayCallBack = done;
         timer = setTimeout(function():void
         {
            if(completed || generation != researchBatchGeneration || !researchBatchBusy) return;
            completed = true; researchBatchBusy = false; researchBatchGeneration++;
            researchBatchReason = "timeout";
            researchBatchFailures.push({route:route,error:"timeout"});
            showObserver("读取超时，已保留" + researchBatchReports.length + "份；可导出部分包");
         },35000);
         researchBatchTimer = timer;
         ApplicationFacade.getInstance().sendNotification("cmdRequestServer",request);
      }

      private static function researchReadRankPage() : void
      {
         if(!researchBatchBusy) return;
         if(researchBatchPage > 100) { researchFinishBatch("page_limit"); return; }
         researchRequest("scene.onlineCopyHandler.getRank",{index:researchBatchConfig.activity,type:researchBatchConfig.role,page:researchBatchPage},function(reply:Object):void
         {
            if(reply == null || reply.code != 200 || !(reply.rows is Array))
            { researchFinishBatch("server_error"); return; }
            var fresh:int = 0;
            var beyond:Boolean = false;
            researchBatchPending = [];
            for each(var value:Object in reply.rows)
            {
               var row:Object;
               try { row = value is String ? JSON.parse(String(value)) : value; }
               catch(error:Error) { researchBatchFailures.push({error:"invalid_rank_row"}); continue; }
               if(row == null || row.rank == null || isNaN(Number(row.rank)) || Number(row.rank) < 0)
               { researchBatchFailures.push({error:"missing_rank"}); continue; }
               var key:String = String(row.reportId != null ? row.reportId : row.id);
               if(researchBatchSeen[key]) continue;
               researchBatchSeen[key] = true; researchBatchSeenCount++; fresh++;
               var rank:int = int(row.rank) + 1;
               if(researchBatchConfig.mode == "range")
               {
                  if(rank < researchBatchConfig.startRank) continue;
                  if(rank > researchBatchConfig.endRank) { beyond = true; continue; }
               }
               if(row.reportId == null || String(row.reportId).length == 0)
               { researchBatchFailures.push({rank:row.rank,error:"missing_report_id"}); continue; }
               researchBatchPending.push(row);
            }
            researchBatchMax = int(reply.maxCount);
            researchBatchExhausted = reply.rows.length == 0 || fresh == 0 || beyond ||
               (researchBatchMax > 0 && researchBatchSeenCount >= researchBatchMax);
            researchReadNextReport();
         });
      }

      private static function researchReadNextReport() : void
      {
         if(!researchBatchBusy) return;
         if(researchBatchConfig.mode == "count" && researchBatchReports.length >= researchBatchConfig.count)
         { researchFinishBatch("target_reached"); return; }
         if(researchBatchPending.length == 0)
         {
            if(researchBatchExhausted) { researchFinishBatch("range_or_board_exhausted"); return; }
            researchBatchPage++; researchReadRankPage(); return;
         }
         var row:Object = researchBatchPending.shift();
         var generation:int = researchBatchGeneration;
         researchRequest("copyReport.copyReportHandler.getReport",{reportId:row.reportId},function(reply:Object):void
         {
            var report:Object = reply != null ? reply.report : null;
            if(reply != null && reply.code == 200 && report != null && String(report.reportId) == String(row.reportId) && report.sceneInfo != null &&
               report.sceneInfo.playerInfos != null && report.sceneInfo.playerInfos.length == 1 &&
               report.sceneInfo.playerInfos[0].p1 != null &&
               report.frames != null && report.frames.length > 0)
            {
               var player:Object = report.sceneInfo.playerInfos[0];
               researchBatchReports.push({metadata:{name:row.name,rank:row.rank,score:row.score,
                  reportId:row.reportId,roleType:researchBatchConfig.role,heart:player.p1.professionType,
                  seed:report.sceneInfo.randomSeed,nativePlaybackVerified:false},response:reply});
            }
            else researchBatchFailures.push({reportId:row.reportId,rank:row.rank,error:"report_unavailable_or_incomplete"});
            showObserver("批量读取：" + researchBatchReports.length + "份；第" + researchBatchPage + "页；完成后点导出录像包");
            setTimeout(function():void { if(generation == researchBatchGeneration && researchBatchBusy) researchReadNextReport(); },200);
         });
      }

      private static function researchFinishBatch(reason:String) : void
      {
         researchBatchBusy = false; researchBatchReason = reason;
         if(researchBatchTimer != 0) clearTimeout(researchBatchTimer);
         showObserver("读取结束：" + researchBatchReports.length + "份，未取得" + researchBatchFailures.length + "份；请点导出录像包");
      }

      private static function researchImportQueue(input:Object) : void
      {
         var samples:Array;
         if(input.format == "zm4-research-queue-v1") samples = input.samples as Array;
         else if(input.format == "zm4-replay-bundle-v1") samples = input.reports as Array;
         else samples = [{label:"单份回放",response:input.response != null ? input.response : input}];
         if(samples == null || samples.length == 0 || samples.length > 1000) throw new Error("队列为空或超出1000份上限");
         researchQueue = JSON.parse(JSON.stringify(samples)) as Array;
         researchQueueIndex = 0; researchQueueRecorded = -1; researchQueueResults = [];
         researchRunResponse(researchQueue[0]);
      }

      private static function researchNextQueue() : void
      {
         if(researchQueueLoading || (!replayFinished && researchOriginal != null)) { showObserver("当前回放正在加载或尚未完成，不能跳到下一份"); return; }
         if(researchQueueIndex + 1 >= researchQueue.length) { researchQueueAuto = false; showObserver("本地队列已结束，可导出批量结果"); return; }
         researchQueueIndex++;
         researchRunResponse(researchQueue[researchQueueIndex]);
      }

      public static function researchAfterComplete(report:Object) : Boolean
      {
         if(report == null || report.lab == null || report.lab.mode != "research_json_v1") return false;
         if(replayAssessment != null && researchQueueRecorded != researchQueueIndex)
         {
            researchQueueResults.push({index:researchQueueIndex,label:researchQueue[researchQueueIndex].label,
               input:researchOriginal,assessment:JSON.parse(JSON.stringify(replayAssessment)),truncated:researchTruncated});
            researchQueueRecorded = researchQueueIndex;
         }
         researchProgressUpdate(QCOnServerFrame2.cliCurrFrame,"本段已结束");
         if(researchQueueAuto && researchQueueIndex + 1 < researchQueue.length)
         {
            setTimeout(function():void { if(researchQueueAuto) researchNextQueue(); },700);
            return true;
         }
         researchQueueAuto = false;
         return false;
      }

      private static var researchManualContext:Object;
      private static var researchManualServer:SimulateServerFrame;
      private static var researchManualPending:Object;
      private static var researchManualRecording:Boolean = false;
      private static var researchManualStopped:Boolean = false;
      private static var researchManualReleasing:Boolean = false;
      private static var researchManualHeld:Object = {};
      private static var researchManualStatus:TextField;

      private static function researchManualMessage(text:String) : void
      {
         if(researchManualStatus != null) researchManualStatus.text = text;
      }

      public static function researchManualResponse(route:String, reply:Object) : void
      {
         if(route == "connector.entryHandler.entry")
         {
            researchManualContext = null; researchManualPending = null;
            researchManualRecording = false; researchManualStopped = false; researchManualServer = null;
            return;
         }
         if(route != "scene.onlineCopyHandler.openZhuXieChallenge") return;
         researchManualContext = null; researchManualPending = null;
         researchManualRecording = false; researchManualStopped = false; researchManualHeld = {};
         if(reply == null || reply.code != 200 || reply.isOnline || Number(reply.dungeonId) != 300109 ||
            reply.userdata == null || reply.userdata.p1 == null || reply.randomSeed == null) return;
         try
         {
            researchManualContext = {userdata:JSON.parse(JSON.stringify(reply.userdata)),randomSeed:reply.randomSeed};
         }
         catch(error:Error) { researchManualContext = null; }
      }

      private static function researchManualBegin(server:SimulateServerFrame) : void
      {
         researchManualServer = null; researchManualPending = null;
         researchManualRecording = false; researchManualStopped = false; researchManualHeld = {};
         var manager:BattleModelManager = BattleModelManager.getIns();
         if(researchManualContext == null || manager.levelInfo == null || manager.levelInfo.id != 300109 ||
            manager.levelParam == null || manager.levelParam.isVideo || manager.levelParam.isMultiplayer) return;
         researchManualServer = server; researchManualRecording = true;
         researchManualMessage("正在临时录制本局手动操作（官方逻辑帧）。点停止后选择保留；默认丢弃。\n停止只松键和停止录制，不暂停Boss或取消正常结算。");
      }

      private static function researchManualBlocked(server:SimulateServerFrame, key:Object) : Boolean
      {
         if(server != researchManualServer || researchManualReleasing) return false;
         if(researchManualStopped && Number(key.key) < 300) return true;
         var code:int = int(key.key);
         if(code < 300) researchManualHeld[String(code)] = JSON.parse(JSON.stringify(key));
         else delete researchManualHeld[String(code - 300)];
         return false;
      }

      private static function researchManualStop(releaseKeys:Boolean) : void
      {
         if(!researchManualRecording || researchManualServer == null) return;
         var server:SimulateServerFrame = researchManualServer;
         if(releaseKeys)
         {
            researchManualReleasing = true;
            try
            {
               for each(var held:Object in researchManualHeld)
               {
                  var up:Object = JSON.parse(JSON.stringify(held)); up.key = int(up.key) + 300; up.objs = [];
                  server.addSendKey(up);
               }
            }
            finally { researchManualReleasing = false; }
         }
         researchManualHeld = {}; researchManualRecording = false; researchManualStopped = releaseKeys;
         try
         {
            var frames:Array = JSON.parse(JSON.stringify(server.frames)) as Array;
            frames.push({currFrame:server.f + 1});
            var wrapper:Object = JSON.parse(JSON.stringify(researchManualContext.userdata));
            var report:Object = {reportId:"local_manual_" + new Date().time,copyId:300109,
               cg:models.managers.GlobalData.CurrCg,sceneInfo:{randomSeed:researchManualContext.randomSeed,
                  playerInfos:[wrapper],score:0},frames:frames,
               playerResult:[{playerId:wrapper.playerId,result:0,bossHp:1,life:0,param:"local_manual_unverified"}],
               lab:{mode:"manual_recording",partial:releaseKeys,runtimeValidated:false,serverBestReplaced:false}};
            researchManualPending = {format:"zm4-research-input-v1",clientVersion:5870,response:{code:200,report:report},
               recording:{source:"native_SimulateServerFrame",partial:releaseKeys,endFrame:server.f,retained:false}};
            researchManualMessage("已停止录制：" + frames.length + "条记录，结束帧" + server.f +
               "。默认不保留。\n点保留并导出，或丢弃。开始下一局/退出存档会丢弃未保留内容。");
         }
         catch(error:Error)
         {
            researchManualPending = null; researchManualMessage("生成临时录像失败：" + String(error));
         }
      }

      private static function researchManualLeave(server:SimulateServerFrame) : void
      {
         if(server != researchManualServer) return;
         if(researchManualRecording) researchManualStop(false);
         researchManualServer = null; researchManualStopped = false;
      }

      private static function researchManualCommand(kind:String) : Boolean
      {
         if(kind == "manual_stop")
         {
            if(researchManualRecording) researchManualStop(true);
            else researchManualMessage(researchManualPending != null ? "本局已停止，可保留导出或丢弃；默认不保留。" : "没有可停止的手动录制。仅支持正常进入魔渊第九层的单人实战。");
            return true;
         }
         if(kind == "manual_discard")
         {
            if(researchManualRecording) researchManualStop(true);
            researchManualPending = null; researchManualStopped = false;
            researchManualMessage("已丢弃本次本地录像，可继续手动操作。不会删除或更改服务器录像。");
            return true;
         }
         if(kind == "manual_keep")
         {
            if(researchManualRecording) { researchManualMessage("请先停止录制，再决定保留；当前仍在临时记录。"); return true; }
            if(researchManualPending == null) { researchManualMessage("没有待保留的本次录像；请先进入第九层手动挑战。"); return true; }
            researchFile = new FileReference();
            researchFile.addEventListener(Event.COMPLETE,function(e:Event):void
            {
               researchManualMessage("本次本地录像已导出。可在网页导入录像JSON中编辑和回放；未替换服务器历史最佳。");
            });
            researchFile.addEventListener(Event.CANCEL,function(e:Event):void
            {
               researchManualMessage("已取消保存，录像仍为临时内容，默认不保留；可重新导出或丢弃。");
            });
            var saved:Object = JSON.parse(JSON.stringify(researchManualPending)); saved.recording.retained = true;
            researchFile.save(JSON.stringify(saved),"zm4_manual_recording.json");
            researchManualStopped = false;
            return true;
         }
         return false;
      }

      private static var researchProgressPanel:Sprite;
      private static var researchProgressText:TextField;
      private static var researchProgressBar:Sprite;
      private static var researchProgressLabel:String = "";
      private static var researchProgressSeed:String = "";
      private static var researchProgressSeedIndex:int = 0;
      private static var researchProgressSeedCount:int = 0;
      private static var researchProgressEnd:int = 0;
      private static var researchProgressActive:Boolean = false;

      private static function researchInstallProgress(s:Stage) : void
      {
         researchProgressPanel = new Sprite(); researchProgressPanel.mouseEnabled = false; researchProgressPanel.mouseChildren = false;
         researchProgressPanel.graphics.beginFill(0x18212C,0.94); researchProgressPanel.graphics.drawRoundRect(0,0,480,104,8,8); researchProgressPanel.graphics.endFill();
         researchProgressPanel.x = Math.max(8,s.stageWidth - 488); researchProgressPanel.y = Math.max(8,s.stageHeight - 112);
         researchProgressText = new TextField(); researchProgressText.defaultTextFormat = new TextFormat("Microsoft YaHei",12,0xFFFFFF);
         researchProgressText.x = 8; researchProgressText.y = 4; researchProgressText.width = 464; researchProgressText.height = 81; researchProgressText.wordWrap = true;
         researchProgressPanel.addChild(researchProgressText); researchProgressBar = new Sprite(); researchProgressBar.x = 8; researchProgressBar.y = 91;
         researchProgressPanel.addChild(researchProgressBar); researchProgressPanel.visible = false; s.addChild(researchProgressPanel);
      }

      private static function researchProgressPrepare(input:Object, report:Object) : void
      {
         researchProgressActive = true; researchProgressSeed = String(report.sceneInfo.randomSeed);
         researchProgressLabel = input.label != null ? String(input.label) : (input.metadata != null && input.metadata.name != null ? String(input.metadata.name) : String(report.reportId));
         researchProgressEnd = int(report.frames[report.frames.length - 1].currFrame);
         var seen:Object = {}; var count:int = 0;
         researchProgressSeedIndex = 0;
         for each(var sample:Object in researchQueue)
         {
            var response:Object = sample.response != null ? sample.response : sample;
            var r:Object = response.report != null ? response.report : response;
            if(r.sceneInfo == null || r.sceneInfo.randomSeed == null) continue;
            var key:String = String(r.sceneInfo.randomSeed);
            if(seen[key]) continue;
            seen[key] = true; count++;
            if(key == researchProgressSeed) researchProgressSeedIndex = count;
         }
         researchProgressSeedCount = count;
         researchProgressUpdate(0,"加载中");
      }

      private static function researchProgressUpdate(frame:int, phase:String) : void
      {
         if(!researchProgressActive || researchProgressPanel == null) return;
         var ratio:Number = researchProgressEnd > 0 ? Math.max(0,Math.min(1,Number(frame) / researchProgressEnd)) : 0;
         researchProgressPanel.visible = true;
         researchProgressPanel.x = Math.max(8,researchStage.stageWidth - 488);
         researchProgressPanel.y = Math.max(8,researchStage.stageHeight - 112);
         if(researchProgressPanel.parent == researchStage) researchStage.setChildIndex(researchProgressPanel,researchStage.numChildren - 1);
         researchProgressText.text = "回放 " + (researchQueueIndex + 1) + "/" + researchQueue.length + "；种子 " + researchProgressSeedIndex + "/" + researchProgressSeedCount + "：" + researchProgressSeed +
            "\n" + researchProgressLabel + "\n" + phase + "；逻辑帧 " + frame + "/" + researchProgressEnd + "（" + (ratio * 100).toFixed(1) + "%）" +
            "\n队列已完成 " + researchQueueResults.length + "/" + researchQueue.length + "；后续连测" + (researchQueueAuto ? "开启" : "关闭");
         researchProgressBar.graphics.clear(); researchProgressBar.graphics.beginFill(0x425466); researchProgressBar.graphics.drawRect(0,0,464,6); researchProgressBar.graphics.endFill();
         researchProgressBar.graphics.beginFill(0x4DC9A0); researchProgressBar.graphics.drawRect(0,0,464 * ratio,6); researchProgressBar.graphics.endFill();
      }

      // Diagnostic input automation. Does not change seed, attributes or game result.
      private static var macroSamples:Array = [];
      private static var macroSelected:int = 0;
      private static var macroArmed:Boolean = false;
      private static var macroAutoRetry:Boolean = true;
      private static var macroStage:Stage;
      private static var macroLabel:TextField;
      private static var macroControls:Sprite;
      private static var macroHotkeys:Object = {};
      private static var macroActive:SimulateServerFrame;
      private static var macroLoaders:Array = [];
      private var macroRunning:Boolean = false;
      private var macroSchedule:Object;
      private var macroHeld:Object = {};
      private var macroLastFrame:int = -1;
      private var macroEvents:Array = [];
      private var macroUser:UserVO;
      private var macroSource:Object;

      public static function installControl(s:Stage) : void
      {
         if(s == null || macroStage != null) return;
         macroStage = s;
         s.addEventListener("keyDown",onMacroControl,true,10000);
         s.addEventListener("keyUp",onMacroKeyUp,true,10000);
         s.addEventListener("keyDown",onMacroControl,false,10000);
         s.addEventListener("keyUp",onMacroKeyUp,false,10000);
         s.addEventListener("deactivate",onMacroFocusLost);
         macroLabel = new TextField();
         macroLabel.width = 480;
         macroLabel.height = 46;
         macroLabel.x = Math.max(8,s.stageWidth-488);
         macroLabel.y = 320;
         macroLabel.background = true;
         macroLabel.backgroundColor = 0x18212C;
         macroLabel.textColor = 0xFFFFFF;
         macroLabel.defaultTextFormat = new TextFormat("Microsoft YaHei",12,0xFFFFFF);
         macroLabel.mouseEnabled = false;
         s.addChild(macroLabel);
         macroControls = new Sprite();
         macroControls.x = Math.max(8,s.stageWidth-488);
         macroControls.y = 368;
         s.addChild(macroControls);
         addMacroButton("切换样本",117,0);
         addMacroButton("持续预备/取消",119,120);
         addMacroButton("急停",120,240);
         addMacroButton("自动重试开关",118,360);
         showMacro("未预备；可点下方按钮，或F6切换／F8预备／F9急停");
         emitMacro({event:"controls_ready",version:2});
      }

      private static function addMacroButton(text:String,code:int,xpos:int) : void
      {
         var button:Sprite = new Sprite();
         button.name = String(code);
         button.x = xpos;
         button.buttonMode = true;
         button.graphics.beginFill(code == 120 ? 0xA83232 : 0x275D88);
         button.graphics.drawRoundRect(0,0,118,28,6,6);
         button.graphics.endFill();
         var label:TextField = new TextField();
         label.defaultTextFormat = new TextFormat("Microsoft YaHei",13,0xFFFFFF,true);
         label.text = text;
         label.x = 5;
         label.y = 3;
         label.width = 110;
         label.height = 24;
         label.mouseEnabled = false;
         label.selectable = false;
         button.addChild(label);
         button.addEventListener("click",onMacroClick);
         macroControls.addChild(button);
      }

      private static function onMacroClick(e:MouseEvent) : void
      {
         e.stopImmediatePropagation();
         handleMacroCommand(int(e.currentTarget.name));
      }

      private static function onMacroFocusLost(e:Event) : void
      {
         macroHotkeys = {};
      }

      private static function showMacro(text:String) : void
      {
         if(macroLabel != null && macroStage != null)
         {
            macroLabel.text = "实战 R6 / " + (macroSamples.length > 0 ? macroSamples[macroSelected].name : "未导入实战操作") + " / 持续预备:" + (macroArmed ? "开" : "关") + " / 自动重试:" + (macroAutoRetry ? "开" : "关") + "\n" + text;
            if(macroLabel.parent == macroStage)
               macroStage.setChildIndex(macroLabel,macroStage.numChildren - 1);
            if(macroControls != null && macroControls.parent == macroStage)
               macroStage.setChildIndex(macroControls,macroStage.numChildren - 1);
         }
         trace("[FRAME_MACRO] " + text);
      }

      private static function onMacroKeyUp(e:KeyboardEvent) : void
      {
         if(e.keyCode == 117 || e.keyCode == 118 || e.keyCode == 119 || e.keyCode == 120)
         {
            e.preventDefault();
            e.stopImmediatePropagation();
            delete macroHotkeys[String(e.keyCode)];
         }
      }

      private static function onMacroControl(e:KeyboardEvent) : void
      {
         if(e.keyCode != 117 && e.keyCode != 118 && e.keyCode != 119 && e.keyCode != 120) return;
         e.preventDefault();
         e.stopImmediatePropagation();
         if(macroHotkeys[String(e.keyCode)]) return;
         macroHotkeys[String(e.keyCode)] = true;
         handleMacroCommand(int(e.keyCode));
      }

      private static function handleMacroCommand(code:int) : void
      {
         if(code == 118) { macroAutoRetry = !macroAutoRetry; showMacro("自动重试：" + (macroAutoRetry ? "开" : "关")); return; }
         if(code == 120)
         {
            macroArmed = false; macroAutoRetry = false;
            if(macroActive != null) macroActive.stopMacro("用户急停",true);
            showMacro("已急停，手动操作可用");
         }
         else if(code == 117)
         {
            if(macroActive != null) return;
            if(macroSamples.length == 0) return;
            macroSelected = (macroSelected + 1) % macroSamples.length;
            macroArmed = false;
            showMacro("已选择；F8预备下一次魔渊第九层");
         }
         else
         {
            if(macroActive != null)
            {
               macroArmed = false;
               macroActive.stopMacro("F8取消",true);
               return;
            }
            if(macroSamples.length == 0) return;
            macroArmed = !macroArmed;
            showMacro(macroArmed ? "已预备：进入单人魔渊第九层时执行；重新挑战继续；F9急停" : "已取消预备");
            emitMacro({event:"armed",armed:macroArmed,sample:(macroSamples.length > 0 ? macroSamples[macroSelected].name : "未导入实战操作")});
         }
      }

      public static function liveDialogSeen(info:Object) : void { emitMacro(info); }
      public static function get liveAutoRetryAllowed() : Boolean { return macroAutoRetry && macroArmed && macroSamples.length > 0; }
      public static function liveResultArrived(win:Boolean) : void
      {
         if(win) { macroArmed = false; macroAutoRetry = false; if(macroActive != null) macroActive.stopMacro("通关成功",true); showMacro("通关成功，已停止持续预备与自动重试，请核对成绩"); }
      }
      public static function liveRetryClicked() : void { showMacro("失败后自动重新挑战；F9急停"); }

      private static function emitMacro(obj:Object) : void
      {
         trace("[FRAME_MACRO] " + JSON.stringify(obj));
      }

      private static function onMacroTelemetry(e:Event) : void
      {
         var loader:URLLoader = e.currentTarget as URLLoader;
         var index:int = macroLoaders.indexOf(loader);
         if(index >= 0) macroLoaders.splice(index,1);
         loader.removeEventListener("complete",onMacroTelemetry);
         loader.removeEventListener("ioError",onMacroTelemetry);
         loader.removeEventListener("securityError",onMacroTelemetry);
      }

      private function beginMacro() : void
      {
         var manager:BattleModelManager = BattleModelManager.getIns();
         if(!macroArmed || manager.levelInfo == null || manager.levelInfo.id != 300109) return;
         if(manager.levelParam == null || manager.levelParam.isVideo || manager.levelParam.isMultiplayer ||
            manager.levelParam.logic == null || manager.levelParam.logic.users.length != 1)
         {
            showMacro("未启动：只支持单人实战第九层");
            return;
         }
         macroUser = manager.levelParam.logic.users[0].getCurrentUVO();
         if(macroUser == null || macroUser.charID != int(macroSamples[macroSelected].charID))
         {
            macroArmed = false;
            showMacro("未启动：角色或心法与导入操作不一致");
            emitMacro({event:"rejected",reason:"requires_wukong_second"});
            return;
         }
         macroSource = macroSamples[macroSelected];
         macroSchedule = macroSource.schedule;
         macroRunning = true;
         macroActive = this;
         emitMacro({event:"started",sample:macroSource.name,sourceReport:macroSource.reportId,
                    sourceSeed:macroSource.seed,sourceEndFrame:macroSource.endFrame,
                    sourceKeyboard:macroSource.keyboard,sourceEvents:macroSource.events,
                    actualCharID:macroUser.charID,actualLevel:macroUser.level,
                    sourceHeart:2,currentFrame:this.f});
         showMacro("执行中：按逻辑帧运行；F9急停。使用本局角色与随机种子");
      }

      private function applyMacroFrame() : void
      {
         if(!macroRunning || macroLastFrame == this.f) return;
         macroLastFrame = this.f;
         var events:Array = macroSchedule[String(this.f)] as Array;
         if(events != null)
         {
            for each(var event:Object in events)
            {
               var sourceCode:int = int(event.key);
               var isUp:Boolean = sourceCode > 300;
               var base:int = isUp ? sourceCode - 300 : sourceCode;
               var action:int = int(macroSource.keyboard[String(base)]);
               var mapped:int = base;
               if(action > 0)
               {
                  mapped = macroUser.keyBoard.getKeyCodeByAction(action);
                  if(mapped <= 0)
                  {
                     stopMacro("技能键位无法匹配，已停止",true);
                     return;
                  }
               }
               var code:int = mapped + (isUp ? 300 : 0);
               recordInput({key:code,objs:[],uid:macroUser.userId,playerIndex:1});
               if(isUp) delete macroHeld[String(mapped)];
               else macroHeld[String(mapped)] = true;
               macroEvents.push({frame:this.f,sourceKey:sourceCode,appliedKey:code,action:action});
            }
         }
         if(this.f > int(macroSource.endFrame))
         {
            stopMacro("源操作序列结束；已松键并交还手动控制，战斗正常继续",true);
            return;
         }
         if(this.f % 30 == 0)
         {
            if(macroEvents.length > 0)
            {
               emitMacro({event:"inputs",sample:macroSource.name,events:macroEvents});
               macroEvents = [];
            }
            showMacro("执行帧 " + this.f + "/" + macroSource.endFrame + "；F9急停");
         }
      }

      private function stopMacro(reason:String,releaseKeys:Boolean) : void
      {
         if(!macroRunning) return;
         if(releaseKeys && _frameObj != null)
         {
            for(var key:String in macroHeld)
               recordInput({key:int(key)+300,objs:[],uid:macroUser.userId,playerIndex:1});
         }
         macroHeld = {};
         emitMacro({event:"stopped",sample:macroSource.name,frame:this.f,reason:reason,events:macroEvents});
         macroEvents = [];
         macroRunning = false;
         macroActive = null;
         showMacro(reason);
      }

      private static function researchLoadLive(input:Object) : void
      {
         if(!models.GameData.playerIsInTown || macroActive != null) throw new Error("请回主城并停止实战操作后导入");
         if(input.clientVersion != 5870 || input.copyId != 300109 || input.sample == null) throw new Error("实战操作版本或副本不匹配");
         var sample:Object = input.sample;
         if(sample.schedule == null || sample.keyboard == null || sample.endFrame < 0 || sample.endFrame > 18000) throw new Error("实战操作不完整");
         if(sample.charID == null) throw new Error("缺少角色心法");
         macroArmed = false; macroSamples = [sample]; macroSelected = 0;
         installControl(researchStage);
         showMacro("已导入。点击实战预备，再手动进入第九层；实战使用服务器本局种子，不修改人物属性");
      }

      public function SimulateServerFrame(param1:Stage)
      {
         _keys = [];
         _saveKeys = [];
         _frames = [];
         _frameObj = {};
         super();
         this.stage = param1;
         param1.addEventListener("enterFrame",onEnterFrame);
         param1.addEventListener("throttle",onThrottle);
         this.id = Math.random() * 10000;
         this.f = 0;
         beginMacro();
         installObserver(param1);
         installSeedBank(param1);
         beginObserver();
         researchManualBegin(this);
      }
      
      public function get frames() : Array
      {
         return this._frames;
      }
      
      public function get frameRate() : Number
      {
         return _frameRate;
      }
      
      protected function onThrottle(param1:ThrottleEvent) : void
      {
         SimpleTextLog.getIns().log2("onThrottle",param1.state,param1.targetFrameRate);
         this.currThrottleState = param1.state;
         this.currThrottleFrameRate = param1.targetFrameRate;
         _throttleTime = 0;
      }
      
      public function advanceTime(param1:Number) : void
      {
         onEnterFrame(null);
      }
      
      public function addSendKey(param1:Object) : void
      {
         if(macroRunning) return;
         recordInput(param1);
      }

      private function recordInput(param1:Object) : void
      {
         var _loc3_:int = 0;
         if(researchManualBlocked(this,param1)) return;
         _keys.push(param1);
         if(_frameObj.hasOwnProperty(this.f) == false)
         {
            _frameObj[this.f] = {
               "playerOper":[{
                  "objs":[],
                  "keys":[],
                  "playerIdIndex":param1.playerIndex - 1
               }],
               "currFrame":this.f,
               "serFrameNum":this.f
            };
            _frames.push(_frameObj[this.f]);
         }
         var _loc2_:Object = _frameObj[this.f].playerOper[0];
         _loc3_ = 0;
         while(_loc3_ < param1.objs.length)
         {
            _loc2_.objs.push(param1.objs[_loc3_]);
            _loc3_++;
         }
         _loc2_.keys.push(param1.key);
      }
      
      public function saveSendKey(param1:Object) : void
      {
      }
      
      private function onEnterFrame(param1:Event) : void
      {
         var _loc3_:Number = NaN;
         if(_deleted || GameFrame.current.isPaused)
         {
            _lastDate = null;
            return;
         }
         _loc3_ = 0.03333333333333333;
         var _loc2_:Date = new Date();
         if(!_lastDate)
         {
            _lastDate = _loc2_;
         }
         var _loc4_:Number = _loc2_.time - _lastDate.time;
         _lastDate = _loc2_;
         _elapsedTime += _loc4_;
         if(this.currThrottleState != "resume" && this.currThrottleFrameRate < 30)
         {
            this._throttleTime += _loc4_;
         }
         if(_elapsedTime < 33)
         {
            return;
         }
         _elapsedTime -= 33;
         this._throttleTime -= 33;
         applyMacroFrame();
         observeFrame();
         if(_testArr)
         {
            k++;
            if(k > _testArr[0])
            {
               _testArr.shift();
               ApplicationFacade.getInstance().sendNotification("OnReceive",_keys);
               _keys.length = 0;
               k = 0;
               if(_testArr.length == 0)
               {
                  _testArr = null;
               }
            }
         }
         else
         {
            k++;
            if(k >= 1)
            {
               ApplicationFacade.getInstance().sendNotification("OnReceive",{
                  "message":_frameObj[this.f],
                  "serFrameNum":this.f
               });
               _keys.length = 0;
               k = 0;
            }
            this.f++;
            _tempFrameRate += _frameRate;
            while(_tempFrameRate > 1)
            {
               _tempFrameRate -= 1;
               ApplicationFacade.getInstance().sendNotification("OnReceive",{
                  "message":_frameObj[this.f],
                  "serFrameNum":this.f
               });
            }
            while(this._throttleTime > 33)
            {
               this._throttleTime -= 33;
               if(this.currThrottleState != "resume" && this.currThrottleFrameRate < 30)
               {
                  ApplicationFacade.getInstance().sendNotification("OnReceive",{
                     "message":_frameObj[this.f],
                     "serFrameNum":this.f
                  });
               }
            }
         }
      }
      
      public function destroy() : void
      {
         researchManualLeave(this);
         finishObserver();
         stopMacro("战斗结束，已松键",true);
         _deleted = true;
         this.stage.removeEventListener("enterFrame",onEnterFrame);
         this.stage.removeEventListener("throttle",onThrottle);
         this.stage = null;
         this._frames = null;
         this._frameObj = null;
      }
      
      public function Slow() : void
      {
         _testArr = [1,2,3,3,4,4,5,5,4,4,3,2,1,1,0,0,0];
      }
      
      public function Start() : void
      {
         GameFrame.stage.addEventListener("enterFrame",onEnterFrame);
      }
      
      public function SetFrameRate(param1:Number) : void
      {
         _frameRate = param1;
      }
   }
}
